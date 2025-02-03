from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
	return "Hello World!"

if __name__ == '__main__':
	# host should be 0.0.0.0 when running in a Docker container
	app.run(host='0.0.0.0')
