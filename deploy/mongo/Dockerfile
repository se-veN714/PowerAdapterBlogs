FROM mongo:8.0

COPY deploy/mongo/entrypoint-wrapper.sh /usr/local/bin/poweradapter-mongo-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/poweradapter-mongo-entrypoint \
    && chmod 0755 /usr/local/bin/poweradapter-mongo-entrypoint

ENTRYPOINT ["poweradapter-mongo-entrypoint"]
CMD ["mongod", "--replSet", "rs0", "--bind_ip_all", "--keyFile", "/data/configdb/keyfile", "--wiredTigerCacheSizeGB", "0.256"]
