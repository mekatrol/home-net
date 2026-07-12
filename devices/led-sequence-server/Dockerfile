FROM node:24-alpine AS web-build
WORKDIR /source/web
COPY src/LedSequence.Web/package*.json ./
RUN npm install
COPY src/LedSequence.Web/ ./
RUN npm run build

FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS api-build
WORKDIR /source
COPY LedSequence.slnx ./
COPY src/LedSequence.Api/LedSequence.Api.csproj src/LedSequence.Api/
RUN dotnet restore src/LedSequence.Api/LedSequence.Api.csproj
COPY src/LedSequence.Api/ src/LedSequence.Api/
COPY --from=web-build /source/web/dist/ src/LedSequence.Api/wwwroot/
RUN dotnet publish src/LedSequence.Api/LedSequence.Api.csproj -c Release --no-restore -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine AS final
WORKDIR /app
COPY --from=api-build /app/ ./
USER app
ENV ASPNETCORE_HTTP_PORTS=8080
ENV SequenceDataPath=/data/controllers.json
EXPOSE 8080
ENTRYPOINT ["dotnet", "LedSequence.Api.dll"]
