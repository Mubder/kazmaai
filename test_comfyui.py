#!/usr/bin/env python3
"""
Quick test for ComfyUI integration.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app"))

from create.comfyui import ComfyUIClient, GenerationRequest


async def test_image_generation():
    """Test image generation with ComfyUI."""
    
    config = {
        "base_url": "http://127.0.0.1:8188",
        "timeout": 120,
        "model": "flux1-dev.safetensors",
    }
    
    client = ComfyUIClient(config)
    
    # Test prompt (Arabic + English)
    prompt = "A beautiful sunset over mountains, golden hour, cinematic lighting"
    
    request = GenerationRequest(
        prompt=prompt,
        negative_prompt="bad quality, worst quality, blurry",
        width=1024,
        height=1024,
        steps=20,
        cfg_scale=7.0,
        seed=42,
    )
    
    print("🎨 Generating image...")
    print(f"Prompt: {prompt}")
    
    result = await client.generate(request)
    
    if result.success:
        print(f"✅ Success!")
        print(f"Generated {len(result.images)} image(s)")
        print(f"Seed: {result.seed}")
        print(f"Execution time: {result.execution_time:.2f}s")
        
        # Save first image
        if result.images:
            import base64
            
            # Remove data:image/png;base64, prefix
            image_data = result.images[0].split(",")[1]
            image_bytes = base64.b64decode(image_data)
            
            output_path = Path("/tmp/kazmaai_test_image.png")
            output_path.write_bytes(image_bytes)
            
            print(f"Saved to: {output_path}")
    else:
        print(f"❌ Failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(test_image_generation())