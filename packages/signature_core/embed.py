"""Single-branch embedding extraction for serving."""
import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from signature_core.model import CustomSiameseCNN
from signature_core.preprocess import UnifiedSignatureTransform


class Embedder:
    def __init__(self, model: CustomSiameseCNN) -> None:
        torch.set_num_threads(1)
        model.eval()  # mandatory: BatchNorm1d in fc crashes on batch of 1 in train mode
        self._model = model
        self._transform = transforms.Compose([UnifiedSignatureTransform(), transforms.ToTensor()])

    @classmethod
    def load(cls, weights_path: str) -> "Embedder":
        model = CustomSiameseCNN()
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        return cls(model)

    def embed(self, img: Image.Image) -> np.ndarray:
        tensor = self._transform(img.convert("L")).unsqueeze(0)
        with torch.no_grad():
            vec = self._model.forward_once(tensor)
        return vec.squeeze(0).numpy().astype(np.float32)
