# Docker Management Commands

## Starting the Application
To start all services in the background:
```bash
docker-compose up -d
```

To start and see the logs:
```bash
docker-compose up
```

## Stopping the Application
To stop all services:
```bash
docker-compose stop
```

To stop and remove containers, networks, and images:
```bash
docker-compose down
```

## Monitoring
To check current status of containers:
```bash
docker-compose ps
```

To view logs for all services:
```bash
docker-compose logs -f
```

To view logs for a specific service (e.g., backend):
```bash
docker-compose logs -f backend
```

## Individual Container Management
If the containers already exist (but are stopped), you can start them by name:
```bash
docker start ai_interviewer_db ai_interviewer_backend ai_interviewer_frontend ai_interviewer_pgadmin
```

To stop them:
```bash
docker stop ai_interviewer_frontend ai_interviewer_backend ai_interviewer_pgadmin ai_interviewer_db
```
