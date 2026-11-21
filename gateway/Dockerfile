# Kong gateway image with the declarative config baked in (used for cloud deployment).
# Build from the repository root:
#   docker build -f gateway/Dockerfile -t tuition-gateway .
# Required at runtime: JWT_SECRET and API_UPSTREAM (e.g. http://tuition-api).
FROM kong:3.9

ENV KONG_DATABASE=off \
    KONG_PROXY_LISTEN=0.0.0.0:8000 \
    KONG_ADMIN_LISTEN=off \
    KONG_STATUS_LISTEN=0.0.0.0:8100 \
    KONG_PROXY_ACCESS_LOG=/dev/stdout \
    KONG_PROXY_ERROR_LOG=/dev/stderr

COPY gateway/kong.yml /kong/kong.yml
COPY gateway/start-kong.sh /kong/start-kong.sh

EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/kong/start-kong.sh"]
