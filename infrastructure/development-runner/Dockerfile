# The original full-trace goldens record Python 3.11.9. Match the environment;
# never rewrite those goldens or the game's trusted regression tests.
ARG PYTHON_BASE=python:3.11.9-slim
FROM ${PYTHON_BASE}
COPY requirements.txt /runner-requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check --timeout 60 --retries 2 -r /runner-requirements.txt
USER 10001:10001
CMD ["python", "--version"]
