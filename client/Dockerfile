# GoE federated comparison -- FEM client task image.
# Build from the repository root so the Snakemake workflow can be copied in:
#   docker build -f goe-fem/client/Dockerfile -t goe-fedcomp-client .
FROM python:3.12-slim

RUN pip install --no-cache-dir snakemake==9.23.1 pandas pyyaml

# The node workflow, unchanged. Only round 0 is ever run here.
COPY snakemake--workflow/Snakefile /opt/goe/Snakefile
COPY snakemake--workflow/rules/    /opt/goe/rules/
COPY snakemake--workflow/wrappers/ /opt/goe/wrappers/
COPY goe-fem/client/goe_client.py  /opt/goe/goe_client.py
RUN chmod -R a+rX /opt/goe && chmod 755 /opt/goe/goe_client.py && ln -s /opt/goe/goe_client.py /usr/local/bin/goe-client

# The FEM launcher may run the container as the host uid, which has no home
# and no passwd entry (Snakemake looks up the user name via getpass).
ENV HOME=/tmp XDG_CACHE_HOME=/tmp/.cache USER=goe

# No ENTRYPOINT: FEM passes the full command ("goe-client --node ...").
CMD ["goe-client", "--help"]
