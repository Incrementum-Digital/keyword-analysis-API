web: gunicorn app:app --workers ${WORKERS:-4} --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --access-logfile - --error-logfile - --log-level info --timeout 120
