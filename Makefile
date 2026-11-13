.PHONY: build test test-race vet fmt tidy bench run docker

build:
	go build -o bin/volterd ./cmd/volterd

test:
	go test ./...

test-race:
	go test -race ./...

vet:
	go vet ./...

fmt:
	gofmt -w .

tidy:
	go mod tidy

bench:
	go test -bench=. -benchmem ./...

run:
	go run ./cmd/volterd

docker:
	docker build -f deploy/Dockerfile -t volterd:dev .
