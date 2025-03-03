# stock-news-crawler
증권1 관련된 뉴스 크롤링 및 관련 정보 수집

## 1차 - 크롤링

### 기타 명령
1. 라이브러리 설치
```
pip install -r requirements.txt
```

2. 도커 mongodb 실행
* 도커 접속 url : http://wicean:1234@localhost:8080
```
docker run --name mongodb -e MONGODB_INITDB_ROOT_USERNAME=wicean -e MONGODB_INITDB_ROOT_PASSWORD=1234 -p 27017:27017 -d mongodb/mongodb-community-server:latest
```
```yml
version: '3.8'

services:
  mongodb:
    image: mongodb/mongodb-community-server:latest
    container_name: mongodb
    environment:
      - MONGODB_INITDB_ROOT_USERNAME=wicean
      - MONGODB_INITDB_ROOT_PASSWORD=1234
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    restart: unless-stopped

volumes:
  mongodb_data:
```

3. 크롤링 실행
```
python main.py
```
