build:
	pylint --rcfile=.pylintrc *.py apiserver/ tests/
	docker build -t apiserver .

run:
	# This target is just to run the apiserver application and assumes all other
	# required resources (mysql) are running. Use launch-stack target instead
	docker run -ti --rm -p 5000:5000 -e FLASK_APP=application.py -e FLASK_ENV=development --name apiserver apiserver

test:	# This target is basically the same as the Github Action Workflow to lint and unit test locally
	pylint --rcfile=.pylintrc *.py apiserver/ tests/
	coverage run -m pytest
	coverage html && open htmlcov/index.html

launch-stack:
	# This target launches all requirements to run apiserver app
	docker compose up -d
