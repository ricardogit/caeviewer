"""CAE Viewer entry point."""
import os
from app import create_app

app = create_app(os.getenv('FLASK_ENV', 'development'))

if __name__ == '__main__':
    port = int(os.getenv('API_PORT', 8080))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'
    print(f"[INFO] CAE Viewer starting on http://localhost:{port}")
    print(f"[INFO] Viewer UI: http://localhost:{port}/step-view/")
    app.run(host='0.0.0.0', port=port, debug=debug)
