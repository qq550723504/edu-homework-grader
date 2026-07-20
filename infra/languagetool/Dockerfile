FROM maven:3.9.9-eclipse-temurin-17 AS build

ARG LANGUAGETOOL_REF=e807fcde6a6506191e1470744d2345da28c26be6

RUN git clone --filter=blob:none https://github.com/languagetool-org/languagetool.git /src \
    && cd /src \
    && git checkout --detach "${LANGUAGETOOL_REF}" \
    && test "$(git rev-parse HEAD)" = "${LANGUAGETOOL_REF}" \
    && ./build.sh languagetool-standalone package -DskipTests

FROM eclipse-temurin:17-jre-jammy

RUN apt-get update \
    && apt-get install --yes --no-install-recommends unzip wget \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/languagetool-standalone/target/LanguageTool-6.8.zip /tmp/languagetool.zip

RUN unzip -q /tmp/languagetool.zip -d /opt \
    && mv /opt/LanguageTool-6.8 /opt/languagetool \
    && rm /tmp/languagetool.zip

EXPOSE 8010

HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD wget -q -O - http://localhost:8010/v2/languages > /dev/null || exit 1

CMD ["java", "-cp", "/opt/languagetool/languagetool-server.jar", "org.languagetool.server.HTTPServer", "--port", "8010", "--public"]
