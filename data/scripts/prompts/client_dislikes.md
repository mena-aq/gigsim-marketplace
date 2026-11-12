You are helping build a simulated freelance marketplace. For each client listed below,
write 2-3 realistic "hidden preferences" expressed as things this client DISLIKES seeing
in freelancer proposals. These are used by a reply simulator to decide whether the client
responds to a proposal.

Clients:
{clients_block}

Rules:
- Each dislike must be a short phrase (max 12 words), e.g. "copy-pasted cover letters".
- Dislikes must be plausible for a freelance client hiring in the client's category.
- Do NOT include anything offensive, personal or identifying.
- Respond with ONLY valid JSON in exactly this shape:

{{
  "clients": [
    {{"id": "<client id>", "dislikes": ["<dislike 1>", "<dislike 2>"]}}
  ]
}}
