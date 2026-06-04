#!/bin/bash
# Employee Portal - Quick Start Script

echo "================================================"
echo "   Employee Management Portal"
echo "================================================"

source venv/bin/activate

echo "Running migrations..."
python manage.py migrate --run-syncdb 2>&1 | tail -3

echo "Seeding sample data..."
python manage.py seed_data 2>/dev/null || echo "  (Data already seeded)"

echo ""
echo "================================================"
echo "  Starting server at http://127.0.0.1:8080"
echo "================================================"
echo ""
echo "  Login Credentials:"
echo "  Admin:    admin / admin123"
echo "  Manager:  manager1 / mgr123"
echo "  Employee: ahmed / emp123"
echo "           (sara, bilal, ayesha, usman / emp123)"
echo ""
echo "  Press Ctrl+C to stop"
echo "================================================"

python manage.py runserver 8080
