# GoE federated comparison -- FEM client task image.
# Build from the repository root:
#   docker build -f client/Dockerfile -t goe-fedcomp-client .
FROM python:3.12-slim

RUN pip install --no-cache-dir snakemake==9.23.1 pandas pyyaml

# The node workflow, unchanged. Only round 0 is ever run here.
COPY workflow/Snakefile /opt/goe/Snakefile
COPY workflow/rules/    /opt/goe/rules/
COPY workflow/wrappers/ /opt/goe/wrappers/
COPY client/goe_client.py  /opt/goe/goe_client.py
RUN chmod -R a+rX /opt/goe && chmod 755 /opt/goe/goe_client.py && ln -s /opt/goe/goe_client.py /usr/local/bin/goe-client

# The FEM launcher may run the container as the host uid, which has no home
# and no passwd entry (Snakemake looks up the user name via getpass).
ENV HOME=/tmp XDG_CACHE_HOME=/tmp/.cache USER=goe

# No ENTRYPOINT: FEM passes the full command ("goe-client --node ...").
CMD ["goe-client", "--help"]
