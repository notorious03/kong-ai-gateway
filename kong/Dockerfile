FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# curl-minimal은 그대로 두고 wget으로 Kong 리포 설정 스크립트 다운로드
RUN dnf install -y wget bash shadow-utils && dnf clean all

# Kong 공식 리포 설정 스크립트로 dnf 리포 등록 후 설치
RUN wget -q -O /tmp/kong-setup.sh \
    https://packages.konghq.com/public/gateway-39/setup.rpm.sh \
    && bash /tmp/kong-setup.sh \
    && rm /tmp/kong-setup.sh \
    && dnf install -y kong \
    && dnf clean all

RUN mkdir -p /usr/local/kong/logs /kong

COPY start.sh /kong/start.sh
RUN chmod +x /kong/start.sh

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD kong health || exit 1

CMD ["/bin/bash", "/kong/start.sh"]
