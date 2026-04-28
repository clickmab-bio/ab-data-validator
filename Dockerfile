ARG BASE_IMAGE=mambaorg/micromamba:1.5.10
FROM ${BASE_IMAGE}

ARG CONDA_MIRROR=https://repo.anaconda.com
ARG CONDA_CUSTOM_CHANNEL_ROOT=https://conda.anaconda.org
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN printf '%s\n' \
    'channels:' \
    '  - conda-forge' \
    '  - bioconda' \
    'show_channel_urls: true' \
    'repodata_use_zst: false' \
    'repodata_fns:' \
    '  - repodata.json' \
    'default_channels:' \
    "  - ${CONDA_MIRROR}/pkgs/main" \
    "  - ${CONDA_MIRROR}/pkgs/r" \
    "  - ${CONDA_MIRROR}/pkgs/msys2" \
    'custom_channels:' \
    "  conda-forge: ${CONDA_CUSTOM_CHANNEL_ROOT}" \
    "  bioconda: ${CONDA_CUSTOM_CHANNEL_ROOT}" \
    > "/home/${MAMBA_USER}/.condarc" \
    && micromamba create -y -n ab-data-validator -f /tmp/environment.yml \
    && micromamba clean --all --yes

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
RUN micromamba run -n ab-data-validator pip install --no-build-isolation --no-deps -e .

USER root
ENTRYPOINT ["micromamba", "run", "-n", "ab-data-validator", "ab-data-validator"]
