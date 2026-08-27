FROM python:3.11-slim

WORKDIR /srv/securesign

# CPU-only torch, from PyTorch's own index rather than PyPI. The default wheel is a CUDA
# build - 2.9GB of nvidia runtime plus 652MB of Triton - and none of it can execute here:
# the container has no GPU and torch.cuda.is_available() is False. Same weights, same
# arithmetic, a quarter of the image.
#
# Installed before the source is copied, so editing a line of application code no longer
# invalidates the layer that reinstalls torch.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.2" "torchvision>=0.17"

COPY pyproject.toml ./
COPY packages ./packages
COPY backend ./backend
COPY scripts ./scripts
COPY models ./models
# torch and torchvision are already satisfied above, so this resolves only the rest.
RUN pip install --no-cache-dir .

EXPOSE 8000
# On SIGTERM uvicorn stops accepting and drains in-flight requests; unbounded, a stuck
# request holds shutdown forever, and compose's stop timer must outlast this one or the
# drain is cut short by SIGKILL mid-verification anyway.
CMD ["uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
