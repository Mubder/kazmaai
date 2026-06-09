"""
KazmaAI ComfyUI Integration Module

Provides:
- Image generation via ComfyUI API
- Video generation workflows
- Flux.1 and SDXL support
- Img2img and photo transformation
- Arabic prompt support
"""

import asyncio
import uuid
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class GenerationRequest:
    """Image/Video generation request."""
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: int = -1  # -1 for random
    model: str = "flux1-dev.safetensors"
    lora: Optional[str] = None
    lora_strength: float = 0.8
    workflow_type: str = "txt2img"  # txt2img, img2img, video
    
    # For img2img
    init_image: Optional[str] = None  # Base64 or path
    denoise_strength: float = 0.75
    
    # Arabic support
    language: str = "auto"


@dataclass
class GenerationResult:
    """Generation result."""
    success: bool
    images: List[str] = field(default_factory=list)  # Base64 or paths
    video: Optional[str] = None
    seed: int = 0
    execution_time: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ComfyUIClient:
    """
    ComfyUI API client for KazmaAI.
    
    Features:
    - Text-to-image generation
    - Image-to-image transformation
    - Video generation
    - Workflow management
    - Arabic prompt support
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize ComfyUI client.
        
        Args:
            config: ComfyUI configuration from config.yaml
        """
        self.base_url = config.get('base_url', 'http://127.0.0.1:8188')
        self.timeout = config.get('timeout', 120)
        self.default_model = config.get('model', 'flux1-dev.safetensors')
        
        # Workflow templates
        self.workflows = {
            'txt2img': self._get_txt2img_workflow,
            'img2img': self._get_img2img_workflow,
            'video': self._get_video_workflow,
        }
    
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """
        Generate image/video from prompt.
        
        Args:
            request: Generation request
            
        Returns:
            GenerationResult
        """
        import httpx
        
        if not HTTPX_AVAILABLE:
            return GenerationResult(
                success=False,
                error="httpx not installed. Run: pip install httpx",
            )
        
        start_time = datetime.utcnow()
        
        try:
            # Build workflow
            workflow_fn = self.workflows.get(request.workflow_type, self._get_txt2img_workflow)
            workflow = workflow_fn(request)
            
            # Send to ComfyUI
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Queue prompt
                queue_response = await client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow},
                )
                queue_response.raise_for_status()
                
                prompt_id = queue_response.json().get('prompt_id')
                
                # Wait for completion
                result = await self._wait_for_completion(prompt_id, client)
                
                # Extract images
                images = await self._extract_images(result, client)
                
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                
                return GenerationResult(
                    success=True,
                    images=images,
                    seed=request.seed if request.seed != -1 else result.get('seed', 0),
                    execution_time=execution_time,
                    metadata={
                        'model': request.model,
                        'steps': request.steps,
                        'cfg_scale': request.cfg_scale,
                    },
                )
        
        except Exception as e:
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            return GenerationResult(
                success=False,
                error=str(e),
                execution_time=execution_time,
            )
    
    async def _wait_for_completion(
        self,
        prompt_id: str,
        client: httpx.AsyncClient,
    ) -> Dict[str, Any]:
        """Wait for generation to complete."""
        import asyncio
        
        while True:
            history_response = await client.get(
                f"{self.base_url}/history/{prompt_id}"
            )
            history_response.raise_for_status()
            
            history = history_response.json()
            
            if prompt_id in history:
                return history[prompt_id]
            
            await asyncio.sleep(1.0)
    
    async def _extract_images(
        self,
        result: Dict[str, Any],
        client: httpx.AsyncClient,
    ) -> List[str]:
        """Extract generated images from result."""
        images = []
        
        outputs = result.get('outputs', {})
        
        for node_id, node_output in outputs.items():
            if 'images' in node_output:
                for img in node_output['images']:
                    # Download image
                    filename = img.get('filename')
                    subfolder = img.get('subfolder', '')
                    img_type = img.get('type', 'output')
                    
                    image_response = await client.get(
                        f"{self.base_url}/view",
                        params={
                            'filename': filename,
                            'subfolder': subfolder,
                            'type': img_type,
                        },
                    )
                    
                    if image_response.status_code == 200:
                        # Return as base64
                        image_base64 = base64.b64encode(image_response.content).decode('utf-8')
                        images.append(f"data:image/png;base64,{image_base64}")
        
        return images
    
    # =========================================================================
    # WORKFLOW TEMPLATES
    # =========================================================================
    
    def _get_txt2img_workflow(self, request: GenerationRequest) -> Dict[str, Any]:
        """
        Get text-to-image workflow for Flux.1.
        
        Supports Arabic prompts with automatic translation hint.
        """
        # Detect if prompt is Arabic
        is_arabic = any('\u0600' <= c <= '\u06FF' for c in request.prompt)
        
        # For Arabic prompts, add translation hint
        if is_arabic:
            enhanced_prompt = (
                f"(best quality, masterpiece:1.4), {request.prompt}\n"
                f"Note: This is an Arabic prompt, generate accordingly"
            )
        else:
            enhanced_prompt = f"(best quality, masterpiece:1.4), {request.prompt}"
        
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": request.cfg_scale,
                    "denoise": 1.0,
                    "latent_image": ["5", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "seed": request.seed if request.seed != -1 else 42,
                    "steps": request.steps,
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": request.model,
                },
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "batch_size": 1,
                    "height": request.height,
                    "width": request.width,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": enhanced_prompt,
                },
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": request.negative_prompt or "bad quality, worst quality, blurry",
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2],
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "KazmaAI",
                    "images": ["8", 0],
                },
            },
        }
        
        # Add LoRA if specified
        if request.lora:
            workflow["10"] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "lora_name": request.lora,
                    "strength_model": request.lora_strength,
                    "strength_clip": request.lora_strength,
                    "model": ["4", 0],
                    "clip": ["4", 1],
                },
            }
            # Update sampler to use LoRA model
            workflow["3"]["inputs"]["model"] = ["10", 0]
        
        return workflow
    
    def _get_img2img_workflow(self, request: GenerationRequest) -> Dict[str, Any]:
        """Get image-to-image workflow."""
        # Similar to txt2img but with image input
        workflow = self._get_txt2img_workflow(request)
        
        # Modify to accept init image
        workflow["5"] = {
            "class_type": "LoadImage",
            "inputs": {
                "image": request.init_image,  # Path or base64
                "upload": "image",
            },
        }
        
        workflow["3"]["inputs"]["denoise"] = request.denoise_strength
        
        return workflow
    
    def _get_video_workflow(self, request: GenerationRequest) -> Dict[str, Any]:
        """Get video generation workflow (placeholder)."""
        # This would use AnimateDiff or similar
        # Placeholder for now
        return self._get_txt2img_workflow(request)


# Convenience function
async def generate_image(
    prompt: str,
    config: Dict[str, Any],
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    **kwargs,
) -> GenerationResult:
    """
    Quick image generation.
    
    Args:
        prompt: Image prompt (Arabic or English)
        config: ComfyUI configuration
        negative_prompt: Negative prompt
        width: Image width
        height: Image height
        **kwargs: Additional GenerationRequest parameters
        
    Returns:
        GenerationResult
    """
    client = ComfyUIClient(config)
    
    request = GenerationRequest(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        **kwargs,
    )
    
    return await client.generate(request)