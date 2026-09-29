# GoE federated comparison -- FEM aggregator task image (standard library only).
# Build from the repository root:
#   docker build -f aggregator/Dockerfile -t goe-fedcomp-aggregator .
FROM python:3.12-slim

COPY workflow/wrappers/filter_bn/bn_math.py /opt/goe/bn_math.py
COPY aggregator/goe_aggregate.py               /opt/goe/goe_aggregate.py
RUN chmod -R a+rX /opt/goe && chmod 755 /opt/goe/goe_aggregate.py && ln -s /opt/goe/goe_aggregate.py /usr/local/bin/goe-aggregate

# No ENTRYPOINT: FEM passes the full command ("goe-aggregate --fst ...").
CMD ["goe-aggregate", "--help"]
