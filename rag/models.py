"""Ollama embedding calls and a lazy, CPU-only ONNX cross-encoder."""

import asyncio
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import httpx
import numpy as np

from rag.config import RagConfig, load_config
from rag.types import RagFailure


class Embeddings:
    def __init__(self, config: RagConfig):
        self.config = config

    async def digest(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.config.ollama_url + "/api/tags")
                response.raise_for_status()
            for item in response.json()["models"]:
                if item["name"] == self.config.embeddings_model:
                    return item["digest"]
        except (httpx.HTTPError, KeyError, ValueError):
            raise RagFailure(
                "model_unavailable", "Ollama is unavailable", True
            ) from None
        raise RagFailure(
            "model_unavailable", "Embedding model missing; run make rag-models"
        )

    async def validate_runtime(self) -> int:
        """Reject a configured embedding budget larger than the runtime accepts."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    self.config.ollama_url + "/api/show",
                    json={"model": self.config.embeddings_model},
                )
                response.raise_for_status()
            data = response.json()
            limits = [
                int(v)
                for k, v in data.get("model_info", {}).items()
                if k.endswith(".context_length")
            ]
            parameter = re.search(
                r"^num_ctx\s+(\d+)\s*$", data.get("parameters", ""), re.MULTILINE
            )
            if parameter:
                limits.append(int(parameter.group(1)))
            if not limits:
                raise ValueError("Missing embedding context metadata")
            limit = min(limits)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise RagFailure(
                "model_unavailable", "Cannot validate embedding runtime context", True
            ) from None
        if self.config.embedding_context_tokens > limit:
            raise RagFailure(
                "embedding_context_mismatch",
                f"Configured embedding limit {self.config.embedding_context_tokens} exceeds runtime limit {limit}",
            )
        return limit

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from tokenizers import Tokenizer

        path = self.config.data_dir / "models/embedding/tokenizer.json"
        if not path.is_file():
            raise RagFailure(
                "model_unavailable",
                "Embedding tokenizer is missing; run make rag-models",
            )
        tokenizer = Tokenizer.from_file(str(path))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        limit = self.config.embedding_context_tokens - 2
        if any(
            len(tokenizer.encode(text, add_special_tokens=False).ids) > limit
            for text in texts
        ):
            raise RagFailure(
                "embedding_context_exceeded",
                f"Embedding text exceeds the {limit}-token input budget",
            )
        vectors = []
        async with httpx.AsyncClient(timeout=120) as client:
            for offset in range(0, len(texts), 16):
                inputs = texts[offset : offset + 16]
                for attempt in range(2):
                    try:
                        response = await client.post(
                            self.config.ollama_url + "/api/embed",
                            json={
                                "model": self.config.embeddings_model,
                                "input": inputs,
                                "truncate": False,
                                "keep_alive": "5m",
                            },
                        )
                        response.raise_for_status()
                        batch = response.json()["embeddings"]
                        if len(batch) != len(inputs):
                            raise ValueError
                        normalized = []
                        for vector in batch:
                            array = np.asarray(vector, dtype=np.float32)
                            norm = np.linalg.norm(array)
                            if (
                                array.shape != (self.config.embedding_dimensions,)
                                or not np.isfinite(array).all()
                                or norm <= 0
                            ):
                                raise ValueError
                            normalized.append((array / norm).tolist())
                        vectors.extend(normalized)
                        break
                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        if (
                            status == 400
                            and "context length" in exc.response.text.lower()
                        ):
                            raise RagFailure(
                                "embedding_context_exceeded",
                                "Embedding runtime rejected input context; check model num_ctx",
                            ) from None
                        retryable = status == 429 or status >= 500
                        failure = RagFailure(
                            "embedding_http_error",
                            f"Embedding request failed with HTTP {status}",
                            retryable,
                        )
                    except (httpx.TimeoutException, httpx.TransportError):
                        failure = RagFailure(
                            "embedding_unavailable",
                            "Embedding transport timed out or disconnected",
                            True,
                        )
                    except (KeyError, ValueError, TypeError):
                        failure = RagFailure(
                            "embedding_response_invalid",
                            "Embedding dimensions, values, or batch shape are invalid",
                        )
                    if not failure.retryable or attempt == 1:
                        raise failure
                    await asyncio.sleep(0.25)
        return vectors


class Reranker:
    def __init__(self, config: RagConfig):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        folder = config.data_dir / "models/reranker"
        installed = (
            json.loads((config.data_dir / "models/manifest.json").read_text())
            if (config.data_dir / "models/manifest.json").is_file()
            else {}
        )
        if (
            installed.get("reranker_revision") != config.reranker_revision
            or installed.get("reranker_model") != config.reranker_model
        ):
            raise RagFailure(
                "model_unavailable",
                "Reranker revision changed or is missing; run make rag-models",
            )
        if (
            not (folder / "model.onnx").is_file()
            or not (folder / "tokenizer.json").is_file()
        ):
            raise RagFailure(
                "model_unavailable", "Reranker is missing; run make rag-models"
            )
        options = ort.SessionOptions()
        options.intra_op_num_threads = config.cpu_threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(folder / "model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def score(self, query: str, passages: list[str]) -> list[float]:
        scores = []
        for offset in range(0, len(passages), 8):
            encodings = self.tokenizer.encode_batch(
                [(query, text) for text in passages[offset : offset + 8]]
            )
            arrays = {
                "input_ids": np.array([item.ids for item in encodings], dtype=np.int64),
                "attention_mask": np.array(
                    [item.attention_mask for item in encodings], dtype=np.int64
                ),
                "token_type_ids": np.array(
                    [item.type_ids for item in encodings], dtype=np.int64
                ),
            }
            outputs = self.session.run(
                None,
                {item.name: arrays[item.name] for item in self.session.get_inputs()},
            )[0].reshape(-1)
            if len(outputs) != len(encodings) or not np.isfinite(outputs).all():
                raise RagFailure("reranking_failed", "Reranker returned invalid scores")
            scores.extend(float(value) for value in outputs)
        return scores


async def download(
    client: httpx.AsyncClient, url: str, destination: Path, *, force: bool = False
) -> None:
    if destination.is_file() and not force:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    async with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        with temporary.open("wb") as output:
            async for data in response.aiter_bytes():
                output.write(data)
    os.replace(temporary, destination)


async def setup_models() -> None:
    config = load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(config.data_dir).free < 600 * 1024**2:
        raise SystemExit("At least 600 MB of free space is required before model setup")
    installed_path = config.data_dir / "models/manifest.json"
    installed = (
        json.loads(installed_path.read_text()) if installed_path.is_file() else {}
    )
    tokenizer_changed = installed.get("tokenizer_revision") != config.tokenizer_revision
    reranker_changed = (
        installed.get("reranker_revision") != config.reranker_revision
        or installed.get("reranker_model") != config.reranker_model
    )
    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            config.ollama_url + "/api/pull",
            json={"model": config.embeddings_model, "stream": False},
        )
        response.raise_for_status()
        tokenizer = config.data_dir / "models/embedding/tokenizer.json"
        cache = (
            Path.home()
            / ".cache/huggingface/hub"
            / ("models--" + config.tokenizer_model.replace("/", "--"))
            / "snapshots"
            / config.tokenizer_revision
            / "tokenizer.json"
        )
        if (not tokenizer.exists() or tokenizer_changed) and cache.is_file():
            tokenizer.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache, tokenizer)
        await download(
            client,
            f"https://huggingface.co/{config.tokenizer_model}/resolve/{config.tokenizer_revision}/tokenizer.json",
            tokenizer,
            force=tokenizer_changed and not cache.is_file(),
        )
        for remote, local in (
            ("tokenizer.json", "tokenizer.json"),
            (config.reranker_file, "model.onnx"),
        ):
            await download(
                client,
                f"https://huggingface.co/{config.reranker_model}/resolve/{config.reranker_revision}/{remote}",
                config.data_dir / "models/reranker" / local,
                force=reranker_changed,
            )
    files = {
        str(path.relative_to(config.data_dir)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in (
            tokenizer,
            config.data_dir / "models/reranker/tokenizer.json",
            config.data_dir / "models/reranker/model.onnx",
        )
    }
    info = {
        "embedding_model": config.embeddings_model,
        "embedding_digest": await Embeddings(config).digest(),
        "tokenizer_revision": config.tokenizer_revision,
        "reranker_model": config.reranker_model,
        "reranker_revision": config.reranker_revision,
        "files": files,
    }
    (config.data_dir / "models/manifest.json").write_text(
        json.dumps(info, indent=2) + "\n"
    )
    print("Prepared Ollama embeddings and pinned CPU tokenizer/reranker artifacts")


if __name__ == "__main__":
    asyncio.run(setup_models())
