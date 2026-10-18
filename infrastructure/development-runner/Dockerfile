# The original full-trace goldens record Python 3.11.9. Match the environment;
# never rewrite those goldens or the game's trusted regression tests.
FROM python:3.11.9-slim
COPY requirements.txt /runner-requirements.txt
RUN python -m pip install --no-cache-dir -r /runner-requirements.txt
USER 10001:10001
CMD ["python", "--version"]
