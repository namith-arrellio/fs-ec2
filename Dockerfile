FROM ubuntu:22.04
LABEL maintainer="Arrellio (Specifically the backend devs, Not Andy)" 
LABEL description="FreeSWITCH build from source with modular, debug-friendly setup" 
ENV DEBIAN_FRONTEND=noninteractive
ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:/usr/lib/pkgconfig 
ENV PATH="/usr/local/freeswitch/bin:$PATH" 
# Base build tools 
RUN apt update && apt install -y \ 
build-essential cmake git wget curl pkg-config \ 
libtool libtool-bin autoconf automake bash \ 
software-properties-common ca-certificates gnupg 

# Core dependencies 
RUN apt install -y \ 
libssl-dev libsqlite3-dev libcurl4-openssl-dev libpcre2-dev \ 
libspeex-dev libspeexdsp-dev libsofia-sip-ua-dev libldns-dev \ 
uuid-dev libpq-dev libopus-dev libsndfile1-dev libavformat-dev \ 
libavcodec-dev libavutil-dev libswscale-dev libjpeg-dev libtiff-dev \ 
libedit-dev liblua5.3-dev yasm nasm 

# Build libks and signalwire-c 
RUN git clone https://github.com/signalwire/libks.git /usr/src/libks && \ 
cd /usr/src/libks && cmake . && make -j$(nproc) && make install
 
RUN git clone https://github.com/signalwire/signalwire-c.git /usr/src/signalwire-c && \ 
cd /usr/src/signalwire-c && cmake . && make -j$(nproc) && make install 

# Build spandsp and sofia-sip from source 
RUN git clone https://github.com/freeswitch/spandsp.git /usr/src/spandsp && \ 
cd /usr/src/spandsp && ./bootstrap.sh && ./configure && make -j$(nproc) && make install && ldconfig 
RUN git clone https://github.com/freeswitch/sofia-sip.git /usr/src/sofia-sip && \ 
cd /usr/src/sofia-sip && ./bootstrap.sh && ./configure && make -j$(nproc) && make install && ldconfig 

# Clone and build FreeSWITCH 
RUN git clone https://github.com/signalwire/freeswitch.git /usr/src/freeswitch && \ 
cd /usr/src/freeswitch && chmod +x bootstrap.sh && bash ./bootstrap.sh -j && \ 
# Enable mod_xml_curl for dynamic configuration
sed -i 's|#xml_int/mod_xml_curl|xml_int/mod_xml_curl|' modules.conf && \
./configure && make -j$(nproc) && make install && \ 
make sounds-install && make moh-install 

RUN mkdir -p /usr/local/freeswitch/conf \
             /usr/local/freeswitch/log \
             /usr/local/freeswitch/db \
             /usr/local/freeswitch/recordings \
             /usr/local/freeswitch/storage && \
    chmod -R 755 /usr/local/freeswitch

WORKDIR /usr/src/freeswitch

CMD ["/usr/local/freeswitch/bin/freeswitch", "-nf", "-nonat"]
