build:
	docker build -t apiserver .

run:
	docker run -ti --rm -p 5000:5000 apiserver
