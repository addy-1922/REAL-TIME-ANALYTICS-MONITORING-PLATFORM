# Signal Watch

**Live Demo:** [https://real-time-analytics-monitoring-platform-3.onrender.com](https://real-time-analytics-monitoring-platform-3.onrender.com)

**Signal Watch** is a real-time application monitoring and analytics platform built using **Python, Django 5.2, and Django REST Framework**. It enables developers to ingest, monitor, store, and analyze application events through secure REST APIs.

The platform combines **PostgreSQL** for persistent event storage, **Redis** for caching and real-time communication, and **Celery** for asynchronous task processing and scheduled background jobs.

## Overview

Signal Watch provides a centralized monitoring dashboard where authenticated users can manage their projects, track application activity, investigate errors, monitor slow requests, configure alert rules, and receive real-time notifications.

Each project has a unique API key for secure event ingestion. The platform also supports WebSocket-based live updates, analytics reports, event filtering, and CSV exports.

## Key Features

- **User Authentication:** Registration, login, password management, and user profiles.
- **Project Management:** Create and manage user-owned monitoring projects.
- **Secure API Ingestion:** API-key-based authentication for sending application events.
- **Real-Time Monitoring:** WebSocket-powered project event streams and notifications.
- **Analytics Dashboard:** Track event volumes, error rates, success rates, and response times.
- **Error Monitoring:** Identify application errors and investigate failed requests.
- **Performance Monitoring:** Track slow requests and response-time statistics.
- **Alert Management:** Configure alert rules and process triggers asynchronously.
- **Background Processing:** Celery workers and Beat for scheduled analytics, reports, and cleanup tasks.
- **Redis Integration:** Caching and WebSocket channel communication.
- **Event Management:** Filter, inspect, and export application events as CSV.
- **API Documentation:** OpenAPI schema and Swagger UI.

## Technology Stack

| Category | Technologies |
|---|---|
| Backend | Python, Django 5.2 |
| REST API | Django REST Framework |
| Database | PostgreSQL |
| Caching | Redis |
| Background Tasks | Celery, Celery Beat |
| Real-Time Communication | Django Channels, WebSockets |
| Frontend | HTML, CSS, JavaScript |
| ASGI Server | Uvicorn |
| Static Files | WhiteNoise |
| API Documentation | drf-spectacular, Swagger UI |
| Deployment | Render, Docker |
| Testing | Django Test Framework |

## Live Demo

Visit the deployed application:

[https://real-time-analytics-monitoring-platform-3.onrender.com](https://real-time-analytics-monitoring-platform-3.onrender.com)

The demo database starts empty. Register an account or create an administrator before accessing the monitoring dashboard.
