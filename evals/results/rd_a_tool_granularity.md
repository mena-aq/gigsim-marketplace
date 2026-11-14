# R&D A: tool granularity

Fine-grained tools with rewritten descriptions improve argument accuracy, while coarse tools reduce schema tokens but make more tool/action errors.

Model: `qwen2.5:3b`; tasks: 15; seed: 0.

Configurations: fine = 12 action-level tools; coarse = 3 server-level tools with a required action argument; rewritten = the same 12 tools with disambiguating descriptions. Each task has one known-correct tool and required arguments. Tokens are Ollama prompt+completion tokens, so tool schema overhead is included.

| Config | Tools | Selection accuracy | Argument accuracy | Arg accuracy given selection | Tokens/task | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fine | 12 | 1.000 | 0.867 | 0.867 | 1355.1 | 0 |
| coarse | 3 | 0.667 | 0.533 | 0.800 | 802.0 | 0 |
| rewritten | 12 | 1.000 | 0.933 | 0.933 | 1487.6 | 0 |

Observed pattern: rewritten had the highest argument accuracy; coarse used the fewest tokens but had the lowest selection and argument accuracy.

Argument accuracy counts only tasks where the selected tool and required arguments are both correct. The conditional column scores arguments among tasks where the tool was selected correctly. Coarse tools also require the correct `action` argument.

This measures tool selection and argument construction only. It does not execute tools or measure downstream proposal quality.

Sources: `rd_a_tool_granularity.json` and `rd_a_tool_granularity_observations.jsonl`.
