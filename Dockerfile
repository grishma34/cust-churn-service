# Inference image (REQ-0009): Lambda python base + src/ + the trained
# artifact. Training dependencies never enter this image (claude.md rule 4) —
# only src/requirements.txt is installed. The artifact is baked in, so an
# image digest maps to exactly one model version.
FROM public.ecr.aws/lambda/python:3.14

COPY src/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# src/ contents sit directly on the task root: imports are `shared.*`,
# `data.*`, `handlers.*` — matching how tests import them (pythonpath=src)
COPY src/ ${LAMBDA_TASK_ROOT}/

# the ONE model this image serves (run `python -m training.train` first)
COPY artifacts/model.joblib artifacts/model_meta.json ${LAMBDA_TASK_ROOT}/artifacts/

CMD ["handlers.predict.handler"]
