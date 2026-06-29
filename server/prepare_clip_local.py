"""Generate local CLIP ViT-L/14 tokenizer/config files from the openai-clip package.

This allows diffusers to load Stable Diffusion v1.5 from a single safetensors file
without needing to download anything from HuggingFace.
"""
import gzip
import json
import os
from pathlib import Path

import clip


def generate_clip_local(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    bpe_path = Path(clip.simple_tokenizer.default_bpe())
    raw = gzip.open(bpe_path).read().decode("utf-8").split("\n")
    # First line is version header, then 49152-256-2 merges.
    merges_lines = raw[1:49152 - 256 - 2 + 1]

    # Build vocab the same way SimpleTokenizer does.
    byte_encoder = clip.simple_tokenizer.bytes_to_unicode()
    vocab = list(byte_encoder.values())
    vocab = vocab + [v + "</w>" for v in vocab]
    for merge in merges_lines:
        parts = merge.split()
        if len(parts) == 2:
            vocab.append("".join(parts))
    vocab.extend(["<|startoftext|>", "<|endoftext|>"])
    vocab_dict = {token: idx for idx, token in enumerate(vocab)}

    # Write vocab.json
    with open(output_dir / "vocab.json", "w", encoding="utf-8") as f:
        json.dump(vocab_dict, f, ensure_ascii=False, indent=2)

    # Write merges.txt (CLIPTokenizer expects GPT-2 style merge list)
    with open(output_dir / "merges.txt", "w", encoding="utf-8") as f:
        f.write("#version: 0.2\n")
        for merge in merges_lines:
            f.write(merge + "\n")

    # Write text model config.json
    config = {
        "attention_dropout": 0.0,
        "dropout": 0.0,
        "hidden_act": "quick_gelu",
        "hidden_size": 768,
        "initializer_factor": 1.0,
        "initializer_range": 0.02,
        "intermediate_size": 3072,
        "layer_norm_eps": 1e-05,
        "max_position_embeddings": 77,
        "model_type": "clip_text_model",
        "num_attention_heads": 12,
        "num_hidden_layers": 12,
        "pad_token_id": 1,
        "projection_dim": 768,
        "torch_dtype": "float32",
        "vocab_size": 49408,
    }
    with open(output_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    # Write tokenizer_config.json
    tokenizer_config = {
        "bos_token": "<|startoftext|>",
        "eos_token": "<|endoftext|>",
        "model_max_length": 77,
        "pad_token": "<|endoftext|>",
        "tokenizer_class": "CLIPTokenizer",
    }
    with open(output_dir / "tokenizer_config.json", "w", encoding="utf-8") as f:
        json.dump(tokenizer_config, f, indent=2)

    print(f"CLIP local files prepared at {output_dir}")


if __name__ == "__main__":
    generate_clip_local(Path(__file__).resolve().parent / "clip_local")
