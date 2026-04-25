@echo off
echo Starting AI Interviewer Docker Stack...
docker-compose up -d
echo Current status:
docker-compose ps
pause
