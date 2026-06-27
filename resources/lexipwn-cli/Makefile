all:
	go mod tidy
	GOOS=linux GOARCH=arm64 go build -a -trimpath -gcflags=all="-l -B -e" -ldflags "-s -w"
	mkdir -p ../out
	mv lexipwn ../out/

