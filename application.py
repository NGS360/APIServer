''' NGS360 API Server '''
from flask import current_app
from apiserver import create_app

app = create_app()

@app.route('/')
def hello():
    ''' Hello World '''
    return f"Hello World, from {current_app.config['APP_NAME']}!"

if __name__ == '__main__':
    # host should be 0.0.0.0 when running in a Docker container
    app.run(host='0.0.0.0')
