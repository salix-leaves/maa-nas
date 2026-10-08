FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Shanghai
ENV HOME=/root

# libatomic1    : libMaaCore 唯一外部依赖
# python3       : Web 手动开关
# procps        : pgrep / pkill
# openssh-client: 模拟器没开时 SSH 到 PC 调 MuMuManager
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates tzdata libatomic1 python3 procps openssh-client \
 && rm -rf /var/lib/apt/lists/*

COPY bin/maa                  /usr/local/bin/maa
COPY platform-tools           /opt/platform-tools
COPY data                     /maa/data
COPY entrypoint.sh            /usr/local/bin/entrypoint.sh
COPY run-daily.sh             /usr/local/bin/run-daily.sh
COPY webctl.py                /usr/local/bin/webctl.py
COPY update-maa.sh            /usr/local/bin/update-maa.sh
COPY rotate-log.sh            /usr/local/bin/rotate-log.sh

ENV MAA_CONFIG_DIR=/maa/config \
    MAA_INSTALL_DIR=/usr/local/bin \
    XDG_DATA_HOME=/maa/data \
    MAA_TASK=daily \
    MAA_CRON_TIME=off \
    MAA_WEB_PORT=5599 \
    MAA_WEB_USER=maa \
    MAA_WEB_PASSWORD= \
    MAA_LOG=/maa/log/run.log \
    MAA_LOG_KEEP=5 \
    LD_LIBRARY_PATH=/maa/data/maa/lib:/opt/platform-tools/lib64 \
    PATH=/usr/local/bin:/opt/platform-tools:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/run-daily.sh \
             /usr/local/bin/webctl.py /usr/local/bin/update-maa.sh \
             /usr/local/bin/rotate-log.sh /usr/local/bin/maa

WORKDIR /maa
VOLUME ["/maa/config"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
