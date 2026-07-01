# =============================================================================
# Classroom Emotion Analytics Dashboard
# =============================================================================
# Shiny dashboard that consumes the CSV produced by the FastAPI backend
# and delivers every analysis the project brief calls for:
#
#   1. Emotion frequency distribution
#   2. Emotion variation across lectures
#   3. Engagement score calculation
#   4. Time-based emotional trends
#   5. Cluster lecturers based on engagement
#   6. Cluster student-subject behaviour based on engagement
#   7. Real-time student emotion notification (via httr to /reports/all)
#
# The CSV path is resolved relative to this file so you can launch the app
# from any working directory.
# =============================================================================

# ---- Dependency bootstrap ---------------------------------------------------
required_pkgs <- c(
  "shiny", "shinydashboard", "dplyr", "ggplot2", "readr",
  "tidyr", "lubridate", "DT", "httr", "jsonlite", "scales", "cluster"
)
to_install <- required_pkgs[!required_pkgs %in% installed.packages()[, "Package"]]
if (length(to_install)) install.packages(to_install, repos = "https://cloud.r-project.org")

suppressPackageStartupMessages({
  library(shiny)
  library(shinydashboard)
  library(dplyr)
  library(ggplot2)
  library(readr)
  library(tidyr)
  library(lubridate)
  library(DT)
  library(httr)
  library(jsonlite)
  library(scales)
  library(cluster)
})

# ---- Configuration ----------------------------------------------------------
this_file <- tryCatch(
  normalizePath(sys.frame(1)$ofile),
  error = function(e) NULL
)
if (is.null(this_file) || !nzchar(this_file)) {
  this_file <- file.path(getwd(), "app.R")
}
PROJECT_ROOT  <- dirname(dirname(this_file))
CSV_PATH      <- file.path(PROJECT_ROOT, "data", "emotions_log.csv")
LECTURES_PATH <- file.path(PROJECT_ROOT, "data", "lectures.csv")
API_BASE      <- "http://127.0.0.1:8000"

# Engagement weights kept in sync with app/config.py.
EMOTION_WEIGHTS <- c(
  happy = 1.0, surprise = 0.8, neutral = 0.6,
  sad = 0.3, fear = 0.2, angry = 0.2, disgust = 0.1
)
LOW_ENGAGEMENT_THRESHOLD <- 0.4

# ---- Data loading -----------------------------------------------------------
load_emotions <- function() {
  if (!file.exists(CSV_PATH)) {
    return(tibble::tibble(
      student_id = character(),
      timestamp = as.POSIXct(character()),
      emotion = character(),
      confidence = numeric(),
      lecture_id = character(),
      engagement_score = numeric()
    ))
  }
  suppressWarnings(suppressMessages(
    df <- readr::read_csv(
      CSV_PATH,
      col_types = cols(
        student_id = col_character(),
        timestamp = col_character(),
        emotion = col_character(),
        confidence = col_double(),
        lecture_id = col_character(),
        engagement_score = col_double()
      )
    )
  ))
  df %>%
    mutate(
      timestamp = lubridate::ymd_hms(timestamp, quiet = TRUE),
      emotion = tolower(emotion)
    ) %>%
    filter(!is.na(timestamp))
}

load_lectures <- function() {
  if (!file.exists(LECTURES_PATH)) return(NULL)
  suppressWarnings(suppressMessages(
    readr::read_csv(LECTURES_PATH, col_types = cols(.default = col_character()))
  ))
}

# ---- Live API integration ---------------------------------------------------
fetch_live_reports <- function() {
  res <- tryCatch(
    httr::GET(paste0(API_BASE, "/reports/all"), httr::timeout(2)),
    error = function(e) NULL
  )
  if (is.null(res) || httr::status_code(res) != 200) return(NULL)
  payload <- httr::content(res, as = "text", encoding = "UTF-8")
  jsonlite::fromJSON(payload, simplifyDataFrame = TRUE)
}

# =============================================================================
# UI
# =============================================================================
ui <- dashboardPage(
  skin = "blue",
  dashboardHeader(title = "Classroom Engagement"),
  dashboardSidebar(
    sidebarMenu(
      menuItem("Overview",            tabName = "overview",     icon = icon("dashboard")),
      menuItem("Frequency",           tabName = "frequency",    icon = icon("chart-bar")),
      menuItem("Lecture Comparison",  tabName = "comparison",   icon = icon("layer-group")),
      menuItem("Time Trends",         tabName = "trends",       icon = icon("clock")),
      menuItem("Lecturer Clusters",   tabName = "lec_cluster",  icon = icon("chalkboard-teacher")),
      menuItem("Student Clusters",    tabName = "stu_cluster",  icon = icon("users")),
      menuItem("Live Monitor",        tabName = "live",         icon = icon("broadcast-tower")),
      menuItem("Raw Data",            tabName = "raw",          icon = icon("table"))
    ),
    hr(),
    actionButton("refresh", "Refresh Data", icon = icon("sync"), width = "85%"),
    br(), br(),
    div(style = "padding: 0 15px; color: #b8c7ce; font-size: 12px;",
        textOutput("data_status"))
  ),
  dashboardBody(
    tags$head(
      tags$style(HTML("
        .small-box .icon-large { font-size: 60px; }
        .box.box-solid.box-primary > .box-header { background: #3c8dbc; }
        #cam_video { width: 100%; max-width: 480px; border: 2px solid #444;
                     background: #000; border-radius: 4px; }
        #cam_status { font-size: 14px; padding: 12px; background: #f5f5f5;
                      border-radius: 4px; min-height: 60px; }
        #cam_status.alert { background: #ffe0e0; color: #c00; }
      ")),
      # Browser-side camera capture. Streams JPEG frames to FastAPI /analyze
      # via fetch(); the FastAPI CORS middleware lets this work cross-origin
      # (Shiny on :3838, FastAPI on :8000).
      tags$script(HTML("
        let cameraStream = null;
        let captureInterval = null;
        const API_BASE = 'http://127.0.0.1:8000';

        async function startCamera() {
          const studentId = document.getElementById('cam_student_id').value || 'S01';
          const lectureId = document.getElementById('cam_lecture_id').value || 'L_live';
          const intervalSec = parseInt(document.getElementById('cam_interval').value) || 3;
          const status = document.getElementById('cam_status');

          // Register the lecture (idempotent on the backend)
          try {
            await fetch(API_BASE + '/lecture/start', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                lecture_id: lectureId, title: 'Live Demo', lecturer_id: 'prof_live'
              })
            });
          } catch (e) {
            status.classList.add('alert');
            status.innerHTML = '<b>Cannot reach FastAPI at ' + API_BASE +
              '</b><br>Start the backend with: uvicorn main:app --reload';
            return;
          }

          // Request camera access
          try {
            cameraStream = await navigator.mediaDevices.getUserMedia({
              video: { width: 640, height: 480 }, audio: false
            });
            const video = document.getElementById('cam_video');
            video.srcObject = cameraStream;
            video.play();
          } catch (e) {
            status.classList.add('alert');
            status.innerHTML = '<b>Camera access denied:</b> ' + e.message;
            return;
          }

          status.classList.remove('alert');
          status.innerHTML = '<i>Warming up... first frame in ' + intervalSec + 's</i>';

          // Capture loop
          captureInterval = setInterval(async () => {
            const video = document.getElementById('cam_video');
            const canvas = document.getElementById('cam_canvas');
            if (!video.videoWidth) return;
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
            const base64 = dataUrl.split(',')[1];

            try {
              const resp = await fetch(API_BASE + '/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  student_id: studentId,
                  lecture_id: lectureId,
                  image_base64: base64
                })
              });
              if (!resp.ok) {
                status.innerHTML = '<b>API error ' + resp.status + '</b>';
                return;
              }
              const data = await resp.json();
              const score = (data.engagement_score ?? 0).toFixed(2);
              const conf = (data.confidence ?? 0).toFixed(2);
              const alertText = data.alert
                ? '<br><b style=\"color:#c00\">⚠ ' + data.alert + '</b>'
                : '';
              status.classList.toggle('alert', !!data.alert);
              status.innerHTML =
                '<b>Student:</b> ' + data.student_id + ' &nbsp;|&nbsp; ' +
                '<b>Lecture:</b> ' + data.lecture_id + '<br>' +
                '<b>Emotion:</b> ' + data.emotion + ' (conf ' + conf + ') &nbsp;|&nbsp; ' +
                '<b>Engagement:</b> ' + score + ' &nbsp;|&nbsp; ' +
                '<b>Status:</b> ' + data.status +
                alertText;
            } catch (e) {
              status.innerHTML = '<b>Network error:</b> ' + e.message;
            }
          }, intervalSec * 1000);
        }

        function stopCamera() {
          if (captureInterval) { clearInterval(captureInterval); captureInterval = null; }
          if (cameraStream) {
            cameraStream.getTracks().forEach(t => t.stop());
            cameraStream = null;
          }
          const video = document.getElementById('cam_video');
          if (video) video.srcObject = null;
          const status = document.getElementById('cam_status');
          status.classList.remove('alert');
          status.innerHTML = 'Camera stopped.';
        }
      "))
    ),
    tabItems(
      # ----- Overview -----
      tabItem(tabName = "overview",
        fluidRow(
          valueBoxOutput("kpi_frames", width = 3),
          valueBoxOutput("kpi_students", width = 3),
          valueBoxOutput("kpi_lectures", width = 3),
          valueBoxOutput("kpi_engagement", width = 3)
        ),
        fluidRow(
          box(title = "Engagement Distribution", status = "primary",
              solidHeader = TRUE, width = 6,
              plotOutput("overview_engagement_hist", height = "300px")),
          box(title = "Top Emotions", status = "primary",
              solidHeader = TRUE, width = 6,
              plotOutput("overview_top_emotions", height = "300px"))
        )
      ),

      # ----- Frequency -----
      tabItem(tabName = "frequency",
        fluidRow(
          box(width = 12, status = "primary", solidHeader = TRUE,
              title = "Filters",
              fluidRow(
                column(4, selectInput("freq_lecture", "Lecture",
                                      choices = "All", selected = "All")),
                column(4, selectInput("freq_student", "Student",
                                      choices = "All", selected = "All"))
              )
          )
        ),
        fluidRow(
          box(title = "Emotion Frequency Distribution", status = "primary",
              solidHeader = TRUE, width = 12,
              plotOutput("freq_plot", height = "420px"))
        )
      ),

      # ----- Comparison -----
      tabItem(tabName = "comparison",
        fluidRow(
          box(title = "Emotion Composition by Lecture", status = "primary",
              solidHeader = TRUE, width = 12,
              plotOutput("comp_stack", height = "400px"))
        ),
        fluidRow(
          box(title = "Average Engagement by Lecture", status = "primary",
              solidHeader = TRUE, width = 12,
              plotOutput("comp_engagement", height = "350px"))
        )
      ),

      # ----- Trends -----
      tabItem(tabName = "trends",
        fluidRow(
          box(width = 12, status = "primary", solidHeader = TRUE,
              title = "Filters",
              fluidRow(
                column(4, selectInput("trend_lecture", "Lecture",
                                      choices = "All", selected = "All")),
                column(4, selectInput("trend_student", "Student",
                                      choices = "All", selected = "All"))
              )
          )
        ),
        fluidRow(
          box(title = "Engagement Over Time", status = "primary",
              solidHeader = TRUE, width = 12,
              plotOutput("trend_plot", height = "420px"))
        )
      ),

      # ----- Lecturer clusters -----
      tabItem(tabName = "lec_cluster",
        fluidRow(
          box(width = 4, status = "primary", solidHeader = TRUE,
              title = "Cluster Settings",
              sliderInput("k_lecturers", "Number of Clusters (k)",
                          min = 2, max = 6, value = 3),
              p(em("Each lecture is featurised by mean engagement, ",
                   "engagement variance, and the proportion of frames ",
                   "below the low-engagement threshold."))
          ),
          box(width = 8, status = "primary", solidHeader = TRUE,
              title = "Lecture Clusters",
              plotOutput("lec_cluster_plot", height = "350px"))
        ),
        fluidRow(
          box(width = 12, status = "primary", solidHeader = TRUE,
              title = "Cluster Assignments",
              DTOutput("lec_cluster_table"))
        )
      ),

      # ----- Student clusters -----
      tabItem(tabName = "stu_cluster",
        fluidRow(
          box(width = 4, status = "primary", solidHeader = TRUE,
              title = "Cluster Settings",
              sliderInput("k_students", "Number of Clusters (k)",
                          min = 2, max = 6, value = 3),
              p(em("Each (student, lecture) pair becomes one observation, ",
                   "featurised by its engagement and dominant-emotion mix."))
          ),
          box(width = 8, status = "primary", solidHeader = TRUE,
              title = "Student-Subject Clusters",
              plotOutput("stu_cluster_plot", height = "350px"))
        ),
        fluidRow(
          box(width = 12, status = "primary", solidHeader = TRUE,
              title = "Cluster Assignments",
              DTOutput("stu_cluster_table"))
        )
      ),

      # ----- Live monitor -----
      tabItem(tabName = "live",
        fluidRow(
          box(width = 12, status = "warning", solidHeader = TRUE,
              title = "Live Webcam Capture (browser → FastAPI /analyze)",
              fluidRow(
                column(3,
                  tags$label("Student ID", style = "font-weight:bold;"),
                  tags$input(id = "cam_student_id", type = "text",
                             class = "form-control", value = "S01")),
                column(3,
                  tags$label("Lecture ID", style = "font-weight:bold;"),
                  tags$input(id = "cam_lecture_id", type = "text",
                             class = "form-control", value = "L_live")),
                column(2,
                  tags$label("Capture every (s)", style = "font-weight:bold;"),
                  tags$input(id = "cam_interval", type = "number",
                             class = "form-control", value = "3",
                             min = "1", max = "30")),
                column(4, br(),
                  tags$button("▶ Start Camera", id = "cam_start",
                              class = "btn btn-success",
                              onclick = "startCamera()",
                              style = "margin-right:8px;"),
                  tags$button("■ Stop Camera", id = "cam_stop",
                              class = "btn btn-danger",
                              onclick = "stopCamera()"))
              ),
              br(),
              fluidRow(
                column(6,
                  tags$video(id = "cam_video",
                             autoplay = NA, playsinline = NA, muted = NA),
                  tags$canvas(id = "cam_canvas", style = "display:none;")
                ),
                column(6,
                  h4("Latest Detection"),
                  tags$div(id = "cam_status",
                    "Press 'Start Camera' to begin. Your browser will ask ",
                    "for camera permission.")
                )
              )
          )
        ),
        fluidRow(
          box(width = 12, status = "warning", solidHeader = TRUE,
              title = "Real-Time Notifications (httr → FastAPI /reports/all)",
              p("Dashboard refreshes every 60 seconds. Students whose ",
                "engagement falls below the threshold are highlighted."),
              verbatimTextOutput("live_status"))
        ),
        fluidRow(
          box(width = 12, status = "warning", solidHeader = TRUE,
              title = "Active Students",
              DTOutput("live_table"))
        )
      ),

      # ----- Raw data -----
      tabItem(tabName = "raw",
        fluidRow(
          box(width = 12, status = "primary", solidHeader = TRUE,
              title = "Raw Emotion Log",
              DTOutput("raw_table"))
        )
      )
    )
  )
)

# =============================================================================
# Server
# =============================================================================
server <- function(input, output, session) {
  # Auto-refreshing data source. reactivePoll watches the CSV's mtime and
  # only re-reads when it changes — cheap and accurate for our use case.
  # Per project requirements, dashboard refreshes every 60 seconds.
  emotions <- reactivePoll(
    intervalMillis = 60000,
    session = session,
    checkFunc = function() {
      if (file.exists(CSV_PATH)) file.info(CSV_PATH)$mtime else Sys.time()
    },
    valueFunc = load_emotions
  )

  observeEvent(input$refresh, {
    # Force a re-read by touching the dependency. reactivePoll already
    # handles this, but the button gives users an explicit trigger.
    session$reload()
  })

  # Keep filter dropdowns in sync with whatever's in the CSV.
  observe({
    df <- emotions()
    lec_choices <- c("All", sort(unique(df$lecture_id)))
    stu_choices <- c("All", sort(unique(df$student_id)))
    updateSelectInput(session, "freq_lecture", choices = lec_choices,
                      selected = isolate(input$freq_lecture) %||% "All")
    updateSelectInput(session, "freq_student", choices = stu_choices,
                      selected = isolate(input$freq_student) %||% "All")
    updateSelectInput(session, "trend_lecture", choices = lec_choices,
                      selected = isolate(input$trend_lecture) %||% "All")
    updateSelectInput(session, "trend_student", choices = stu_choices,
                      selected = isolate(input$trend_student) %||% "All")
  })

  output$data_status <- renderText({
    df <- emotions()
    if (nrow(df) == 0) {
      "No data yet. Start a lecture and feed frames to /analyze, or run scripts/seed_data.py."
    } else {
      sprintf("%d rows loaded (last update %s)",
              nrow(df), format(max(df$timestamp), "%H:%M:%S"))
    }
  })

  # ----- KPI cards -----
  output$kpi_frames <- renderValueBox({
    df <- emotions()
    valueBox(format(nrow(df), big.mark = ","), "Total Frames",
             icon = icon("camera"), color = "blue")
  })
  output$kpi_students <- renderValueBox({
    df <- emotions()
    valueBox(length(unique(df$student_id)), "Students",
             icon = icon("user-graduate"), color = "green")
  })
  output$kpi_lectures <- renderValueBox({
    df <- emotions()
    valueBox(length(unique(df$lecture_id)), "Lectures",
             icon = icon("chalkboard"), color = "purple")
  })
  output$kpi_engagement <- renderValueBox({
    df <- emotions() %>% filter(!is.na(engagement_score))
    val <- if (nrow(df) == 0) 0 else mean(df$engagement_score)
    valueBox(sprintf("%.2f", val), "Avg Engagement",
             icon = icon("chart-line"),
             color = if (val < LOW_ENGAGEMENT_THRESHOLD) "red" else "yellow")
  })

  # ----- Overview plots -----
  output$overview_engagement_hist <- renderPlot({
    df <- emotions()
    if (nrow(df) == 0) return(empty_plot("No data"))
    ggplot(df, aes(x = engagement_score)) +
      geom_histogram(bins = 20, fill = "#3c8dbc", colour = "white") +
      geom_vline(xintercept = LOW_ENGAGEMENT_THRESHOLD,
                 linetype = "dashed", colour = "red") +
      labs(x = "Engagement Score", y = "Frame Count") +
      theme_minimal(base_size = 13)
  })

  output$overview_top_emotions <- renderPlot({
    df <- emotions()
    if (nrow(df) == 0) return(empty_plot("No data"))
    df %>%
      filter(!emotion %in% c("absent", "error")) %>%
      count(emotion, sort = TRUE) %>%
      ggplot(aes(x = reorder(emotion, n), y = n, fill = emotion)) +
      geom_col(show.legend = FALSE) +
      coord_flip() +
      labs(x = NULL, y = "Frame Count") +
      theme_minimal(base_size = 13)
  })

  # ----- Frequency tab -----
  output$freq_plot <- renderPlot({
    df <- emotions()
    if (nrow(df) == 0) return(empty_plot("No data"))
    if (input$freq_lecture != "All")
      df <- df %>% filter(lecture_id == input$freq_lecture)
    if (input$freq_student != "All")
      df <- df %>% filter(student_id == input$freq_student)

    df %>%
      count(emotion) %>%
      mutate(pct = n / sum(n)) %>%
      ggplot(aes(x = reorder(emotion, n), y = n, fill = emotion)) +
      geom_col(show.legend = FALSE) +
      geom_text(aes(label = scales::percent(pct, accuracy = 0.1)),
                hjust = -0.1, size = 4) +
      coord_flip() +
      scale_y_continuous(expand = expansion(mult = c(0, 0.15))) +
      labs(x = NULL, y = "Frequency") +
      theme_minimal(base_size = 13)
  })

  # ----- Lecture comparison -----
  output$comp_stack <- renderPlot({
    df <- emotions()
    if (nrow(df) == 0) return(empty_plot("No data"))
    df %>%
      count(lecture_id, emotion) %>%
      group_by(lecture_id) %>%
      mutate(prop = n / sum(n)) %>%
      ungroup() %>%
      ggplot(aes(x = lecture_id, y = prop, fill = emotion)) +
      geom_col() +
      scale_y_continuous(labels = scales::percent_format()) +
      labs(x = "Lecture", y = "Proportion of Frames", fill = "Emotion") +
      theme_minimal(base_size = 13)
  })

  output$comp_engagement <- renderPlot({
    df <- emotions()
    if (nrow(df) == 0) return(empty_plot("No data"))
    df %>%
      group_by(lecture_id) %>%
      summarise(mean_eng = mean(engagement_score),
                sd_eng = sd(engagement_score), .groups = "drop") %>%
      ggplot(aes(x = reorder(lecture_id, -mean_eng), y = mean_eng)) +
      geom_col(fill = "#3c8dbc") +
      geom_errorbar(aes(ymin = pmax(mean_eng - sd_eng, 0),
                        ymax = pmin(mean_eng + sd_eng, 1)),
                    width = 0.2) +
      geom_hline(yintercept = LOW_ENGAGEMENT_THRESHOLD,
                 linetype = "dashed", colour = "red") +
      labs(x = "Lecture", y = "Mean Engagement (± SD)") +
      theme_minimal(base_size = 13)
  })

  # ----- Time trends -----
  output$trend_plot <- renderPlot({
    df <- emotions()
    if (nrow(df) == 0) return(empty_plot("No data"))
    if (input$trend_lecture != "All")
      df <- df %>% filter(lecture_id == input$trend_lecture)
    if (input$trend_student != "All")
      df <- df %>% filter(student_id == input$trend_student)
    if (nrow(df) == 0) return(empty_plot("No matching rows"))

    aggregate_by <- if (input$trend_student == "All") "lecture_id" else "student_id"
    df %>%
      ggplot(aes(x = timestamp, y = engagement_score,
                 colour = .data[[aggregate_by]],
                 group = .data[[aggregate_by]])) +
      geom_line(alpha = 0.4) +
      geom_smooth(se = FALSE, method = "loess", span = 0.4) +
      geom_hline(yintercept = LOW_ENGAGEMENT_THRESHOLD,
                 linetype = "dashed", colour = "red") +
      labs(x = "Time", y = "Engagement Score",
           colour = aggregate_by) +
      theme_minimal(base_size = 13)
  })

  # ----- Lecturer clustering -----
  lecturer_features <- reactive({
    df <- emotions()
    if (nrow(df) == 0) return(NULL)
    feats <- df %>%
      group_by(lecture_id) %>%
      summarise(
        mean_engagement = mean(engagement_score),
        var_engagement  = var(engagement_score, na.rm = TRUE),
        low_pct         = mean(engagement_score < LOW_ENGAGEMENT_THRESHOLD),
        n_frames        = n(),
        .groups = "drop"
      ) %>%
      mutate(var_engagement = ifelse(is.na(var_engagement), 0, var_engagement))
    feats
  })

  lecturer_clusters <- reactive({
    feats <- lecturer_features()
    if (is.null(feats) || nrow(feats) < input$k_lecturers) return(NULL)
    mat <- feats %>% select(mean_engagement, var_engagement, low_pct) %>% scale()
    set.seed(42)
    km <- kmeans(mat, centers = input$k_lecturers, nstart = 25)
    feats %>% mutate(cluster = factor(km$cluster))
  })

  output$lec_cluster_plot <- renderPlot({
    feats <- lecturer_clusters()
    if (is.null(feats)) return(empty_plot("Not enough lectures yet"))
    ggplot(feats, aes(x = mean_engagement, y = low_pct,
                      colour = cluster, size = n_frames)) +
      geom_point(alpha = 0.8) +
      geom_text(aes(label = lecture_id), vjust = -1.2, size = 3.5,
                show.legend = FALSE) +
      labs(x = "Mean Engagement", y = "% Low-Engagement Frames",
           colour = "Cluster", size = "Frames") +
      theme_minimal(base_size = 13)
  })

  output$lec_cluster_table <- renderDT({
    feats <- lecturer_clusters()
    if (is.null(feats)) return(NULL)
    feats %>%
      arrange(cluster, desc(mean_engagement)) %>%
      mutate(across(where(is.numeric), \(x) round(x, 3))) %>%
      datatable(options = list(pageLength = 10), rownames = FALSE)
  })

  # ----- Student-subject clustering -----
  student_features <- reactive({
    df <- emotions()
    if (nrow(df) == 0) return(NULL)
    df %>%
      group_by(student_id, lecture_id) %>%
      summarise(
        mean_engagement = mean(engagement_score),
        happy_pct       = mean(emotion == "happy"),
        neutral_pct     = mean(emotion == "neutral"),
        sad_pct         = mean(emotion == "sad"),
        n_frames        = n(),
        .groups = "drop"
      )
  })

  student_clusters <- reactive({
    feats <- student_features()
    if (is.null(feats) || nrow(feats) < input$k_students) return(NULL)
    mat <- feats %>%
      select(mean_engagement, happy_pct, neutral_pct, sad_pct) %>% scale()
    mat[is.nan(mat)] <- 0
    set.seed(42)
    km <- kmeans(mat, centers = input$k_students, nstart = 25)
    feats %>% mutate(cluster = factor(km$cluster))
  })

  output$stu_cluster_plot <- renderPlot({
    feats <- student_clusters()
    if (is.null(feats)) return(empty_plot("Not enough data yet"))
    ggplot(feats, aes(x = mean_engagement, y = happy_pct,
                      colour = cluster, size = n_frames,
                      shape = lecture_id)) +
      geom_point(alpha = 0.85) +
      labs(x = "Mean Engagement", y = "% Happy Frames",
           colour = "Cluster", size = "Frames", shape = "Lecture") +
      theme_minimal(base_size = 13)
  })

  output$stu_cluster_table <- renderDT({
    feats <- student_clusters()
    if (is.null(feats)) return(NULL)
    feats %>%
      arrange(cluster, student_id) %>%
      mutate(across(where(is.numeric), \(x) round(x, 3))) %>%
      datatable(options = list(pageLength = 10), rownames = FALSE)
  })

  # ----- Live monitor (real-time httr integration) -----
  # Polls FastAPI /reports/all every 60 seconds per project spec.
  live_data <- reactivePoll(
    intervalMillis = 60000,
    session = session,
    checkFunc = function() Sys.time(),
    valueFunc = fetch_live_reports
  )

  output$live_status <- renderText({
    d <- live_data()
    if (is.null(d)) {
      paste0("⚠ Cannot reach FastAPI at ", API_BASE,
             ". Start the backend with `uvicorn main:app --reload`.")
    } else if (length(d) == 0 || (is.data.frame(d) && nrow(d) == 0)) {
      "✓ Connected. No active students yet."
    } else {
      n_students <- if (is.data.frame(d)) nrow(d) else length(d)
      sprintf("✓ Connected. Tracking %d student(s).", n_students)
    }
  })

  output$live_table <- renderDT({
    d <- live_data()
    if (is.null(d)) return(NULL)
    df <- if (is.data.frame(d)) d
          else tryCatch(as.data.frame(d), error = function(e) NULL)
    if (is.null(df) || nrow(df) == 0 || ncol(df) == 0) return(NULL)
    keep <- intersect(c("student_id", "total_frames", "attendance_rate",
                        "average_engagement", "current_trend"), names(df))
    if (length(keep) == 0) return(NULL)
    df <- df[, keep, drop = FALSE]
    dt <- datatable(df, options = list(pageLength = 10), rownames = FALSE)
    if ("average_engagement" %in% names(df)) {
      dt <- dt %>% formatStyle(
        "average_engagement",
        backgroundColor = styleInterval(LOW_ENGAGEMENT_THRESHOLD,
                                        c("#ffcccc", "#ccffcc"))
      )
    }
    dt
  })

  # ----- Raw data -----
  output$raw_table <- renderDT({
    df <- emotions()
    if (nrow(df) == 0) return(NULL)
    datatable(df %>% arrange(desc(timestamp)),
              options = list(pageLength = 25), rownames = FALSE)
  })
}

# Helpers --------------------------------------------------------------------
empty_plot <- function(msg) {
  ggplot() +
    annotate("text", x = 0, y = 0, label = msg, size = 6, colour = "grey40") +
    theme_void()
}

`%||%` <- function(a, b) if (is.null(a) || is.na(a) || a == "") b else a

# Run -----------------------------------------------------------------------
shinyApp(ui, server)
