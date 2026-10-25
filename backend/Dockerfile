# AWS Lambda container image for the API. Build from this folder:
#   docker buildx build --platform linux/amd64 --provenance=false -t multirag-api --load .
# (--provenance=false: Lambda rejects images that carry buildx's extra metadata)
FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Bake the embedding models into the image: outside /tmp Lambda's filesystem is read-only,
# and downloading ~200 MB on every cold start would be slow.
ENV FASTEMBED_CACHE_PATH=/opt/models
COPY config.py ${LAMBDA_TASK_ROOT}/
RUN python -c "from config import DENSE_MODEL, SPARSE_MODEL, MODEL_CACHE_DIR as d; \
from fastembed import SparseTextEmbedding, TextEmbedding; \
TextEmbedding(DENSE_MODEL, cache_dir=d); SparseTextEmbedding(SPARSE_MODEL, cache_dir=d)"

# At run time: never reach for the Hugging Face hub, and keep any library cache in writable /tmp
ENV HF_HUB_OFFLINE=1 HF_HOME=/tmp/hf

COPY main.py ${LAMBDA_TASK_ROOT}/
COPY routers ${LAMBDA_TASK_ROOT}/routers
COPY services ${LAMBDA_TASK_ROOT}/services

CMD ["main.handler"]
