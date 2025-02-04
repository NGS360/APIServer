''' NGS360 API Server '''
from apiserver import create_app
from apiserver import models

app = create_app()

if __name__ == '__main__':
    # host should be 0.0.0.0 when running in a Docker container
    app.run(host='0.0.0.0')
