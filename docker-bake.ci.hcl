target "api" {
  tags = ["edu-homework-grader/api:ci"]
  cache-from = ["type=gha,scope=edu-homework-grader-api"]
  cache-to = ["type=gha,mode=max,scope=edu-homework-grader-api"]
}

target "grader" {
  tags = ["edu-homework-grader/grader:ci"]
  cache-from = ["type=gha,scope=edu-homework-grader-grader"]
  cache-to = ["type=gha,mode=max,scope=edu-homework-grader-grader"]
}

target "web" {
  tags = ["edu-homework-grader/web:ci"]
  cache-from = ["type=gha,scope=edu-homework-grader-web"]
  cache-to = ["type=gha,mode=max,scope=edu-homework-grader-web"]
}

target "languagetool" {
  tags = ["edu-homework-grader/languagetool:ci"]
  cache-from = ["type=gha,scope=edu-homework-grader-languagetool"]
  cache-to = ["type=gha,mode=max,scope=edu-homework-grader-languagetool"]
}
