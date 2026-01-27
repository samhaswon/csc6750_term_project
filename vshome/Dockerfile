FROM golang:1.21-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/vshome ./

FROM alpine:3.19
WORKDIR /app
RUN adduser -D -g '' vshome
COPY --from=builder /out/vshome /app/vshome
COPY devices.yaml /app/devices.yaml
COPY web /app/web
USER vshome
EXPOSE 8080
ENTRYPOINT ["/app/vshome"]
