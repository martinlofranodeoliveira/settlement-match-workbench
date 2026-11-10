ARG PREPARED_IMAGE=settlement-match-dependencies:local
FROM ${PREPARED_IMAGE}
USER root
COPY . /opt/settlement-source/
COPY scripts/package_gate.py scripts/record_inventory.py scripts/quality.py /opt/settlement-checks/
RUN mkdir -p /work/distributions /work/evidence /work/home \
 && chown 1000:1000 /work/distributions /work/evidence /work/home \
 && python -I -B /opt/settlement-checks/record_inventory.py /opt/settlement-source /opt/qualification/source-inventory.json
ENV HOME=/work/home PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONHASHSEED=0
WORKDIR /work
USER 1000:1000
ENTRYPOINT []
CMD ["/opt/settlement-build/bin/python", "-I", "-B", "/opt/settlement-checks/package_gate.py", "/opt/settlement-source"]
