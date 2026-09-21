"""Tiny causal Transformer for offline neural-runtime research tests.

Built entirely in-process with PyTorch — no Hugging Face downloads, no GGUF,
no LM Studio coupling. Production HADES must not import this at startup.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from neural.deps import require_torch


@dataclass(frozen=True)
class ToyTransformerConfig:
    vocab_size: int = 64
    hidden_size: int = 32
    num_layers: int = 2
    num_heads: int = 4
    intermediate_size: int = 64
    max_seq_len: int = 32
    seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_toy_causal_lm(config: ToyTransformerConfig | None = None) -> tuple[Any, ToyTransformerConfig]:
    """Construct a tiny causal LM and return ``(model, config)``."""
    torch = require_torch()
    cfg = config or ToyTransformerConfig()
    if cfg.hidden_size % cfg.num_heads != 0:
        raise ValueError("hidden_size must be divisible by num_heads")
    torch.manual_seed(int(cfg.seed))

    class ToyBlock(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.ln1 = torch.nn.LayerNorm(cfg.hidden_size)
            self.attn = torch.nn.MultiheadAttention(
                cfg.hidden_size,
                cfg.num_heads,
                batch_first=True,
            )
            self.ln2 = torch.nn.LayerNorm(cfg.hidden_size)
            self.mlp = torch.nn.Sequential(
                torch.nn.Linear(cfg.hidden_size, cfg.intermediate_size),
                torch.nn.GELU(),
                torch.nn.Linear(cfg.intermediate_size, cfg.hidden_size),
            )

        def forward(self, x: Any) -> Any:
            # Causal mask: True means ignore (PyTorch MHA convention).
            t = x.shape[1]
            causal = torch.triu(torch.ones(t, t, dtype=torch.bool, device=x.device), diagonal=1)
            h = self.ln1(x)
            attn_out, _ = self.attn(h, h, h, attn_mask=causal, need_weights=False)
            x = x + attn_out
            x = x + self.mlp(self.ln2(x))
            return x

    class ToyCausalLM(torch.nn.Module):
        """Minimal decoder-only stack with inspectable ``blocks``."""

        architecture_family = "toy_causal_v1"

        def __init__(self) -> None:
            super().__init__()
            self.config = cfg
            self.tok_emb = torch.nn.Embedding(cfg.vocab_size, cfg.hidden_size)
            self.pos_emb = torch.nn.Embedding(cfg.max_seq_len, cfg.hidden_size)
            self.blocks = torch.nn.ModuleList([ToyBlock() for _ in range(cfg.num_layers)])
            self.ln_f = torch.nn.LayerNorm(cfg.hidden_size)
            self.lm_head = torch.nn.Linear(cfg.hidden_size, cfg.vocab_size, bias=False)

        def forward(self, input_ids: Any) -> Any:
            return self.lm_head(self.forward_hidden(input_ids))

        def forward_hidden(self, input_ids: Any) -> Any:
            """Return last-layer hidden states ``[batch, seq, hidden]`` (no LM head)."""
            if input_ids.ndim != 2:
                raise ValueError("input_ids must be [batch, seq]")
            _b, seq = input_ids.shape
            if seq > cfg.max_seq_len:
                raise ValueError(f"seq_len {seq} exceeds max_seq_len {cfg.max_seq_len}")
            positions = torch.arange(seq, device=input_ids.device).unsqueeze(0)
            x = self.tok_emb(input_ids) + self.pos_emb(positions)
            for block in self.blocks:
                x = block(x)
            return self.ln_f(x)

        def hidden_size(self) -> int:
            return int(cfg.hidden_size)

        def num_layers(self) -> int:
            return int(cfg.num_layers)

    return ToyCausalLM(), cfg


def freeze_module(module: Any) -> None:
    for param in module.parameters():
        param.requires_grad = False


def assert_module_frozen(module: Any) -> None:
    trainable = [name for name, p in module.named_parameters() if p.requires_grad]
    if trainable:
        raise AssertionError(f"expected frozen module; trainable={trainable[:8]}")


def _tensor_raw_bytes(tensor: Any) -> bytes:
    """Serialize contiguous float32 tensor bytes without requiring NumPy."""
    torch = require_torch()
    data = tensor.detach().to(device="cpu", dtype=torch.float32).contiguous()
    try:
        return data.numpy().tobytes()
    except (RuntimeError, AttributeError, ImportError):
        nbytes = int(data.numel()) * int(data.element_size())
        storage = data.untyped_storage()
        offset = int(data.storage_offset()) * int(data.element_size())
        return bytes(storage)[offset : offset + nbytes]


def parameter_checksum(module: Any) -> str:
    """Deterministic checksum of parameter bytes (CPU float32)."""
    import hashlib

    digest = hashlib.sha256()
    for name, param in sorted(module.named_parameters(), key=lambda item: item[0]):
        digest.update(name.encode("utf-8"))
        digest.update(_tensor_raw_bytes(param))
    return digest.hexdigest()
