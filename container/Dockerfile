FROM rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9 AS driver
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
ARG ANKICONNECT_REV=760ff48d8bbcfbc956f57c40475a8ab960c36a9c
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git xvfb gosu \
    libgl1 libegl1 libnss3 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \
    libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 \
    libxcb-render-util0 libdbus-1-3 libasound2 libxcomposite1 libxdamage1 \
    libxrandr2 libxtst6 libxi6 libglib2.0-0 libfontconfig1 libatomic1 libgbm1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/poc \
    && dpkg-query -W > /opt/poc/os-versions.txt
COPY container/requirements.txt /opt/poc/requirements.txt
COPY container/constraints.txt /opt/poc/constraints.txt
RUN pip install --no-cache-dir -r /opt/poc/requirements.txt -c /opt/poc/constraints.txt \
    && pip freeze > /opt/poc/python-versions.txt
RUN git init /opt/anki-connect \
    && git -C /opt/anki-connect remote add origin https://git.sr.ht/~foosoft/anki-connect \
    && git -C /opt/anki-connect fetch --depth 1 origin "$ANKICONNECT_REV" \
    && git -C /opt/anki-connect checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/anki-connect rev-parse HEAD)" = "$ANKICONNECT_REV" \
    && printf '%s\n' "$ANKICONNECT_REV" > /opt/poc/ankiconnect-revision
RUN useradd --create-home --uid 1000 anki && mkdir -p /data /run/poc \
    && chown anki:anki /data /run/poc
COPY --from=driver /build/target/release/anki-poc /usr/local/bin/anki-poc
COPY container/ /opt/poc/
ENV DISPLAY=:99 QTWEBENGINE_CHROMIUM_FLAGS=--disable-dev-shm-usage \
    ANKI_BASE=/data ANKI_PROFILE=POC ANKI_DECK=POC ANKI_MODEL=Basic \
    ANKI_API_KEY_FILE=/run/poc/api-key
ENTRYPOINT ["python3", "/opt/poc/entrypoint.py"]
