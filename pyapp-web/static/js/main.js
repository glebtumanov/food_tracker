// -----------------------------------------------------------------------------
// Основные элементы
// -----------------------------------------------------------------------------
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const previewContainer = document.getElementById("previewContainer");
/* Элементы статического шаблона превью */
const previewImage = document.getElementById("previewImage");
const analysisResult = document.getElementById("analysisResult");
const analyzeButton = document.getElementById("analyzeButton");
const uploadUrl = "/upload";
const saveAnalysisUrl = "/save_analysis";
const analyzeImageUrl = "/analyze_image";

// Текущие данные загрузки
let currentUploadId = null;
let currentFilename = null;

if (!dropZone || !fileInput || !previewContainer) {
  /* DOM не загрузился корректно — прекращаем */
  throw new Error("Не удалось инициализировать элементы интерфейса");
}

// -----------------------------------------------------------------------------
// Вспомогательные функции
// -----------------------------------------------------------------------------
function updatePreview(url, uploadId = null) {
  if (!previewImage) return;

  previewImage.src = url;
  previewImage.classList.remove("d-none");

  // Извлекаем имя файла из URL
  currentFilename = url.split('/').pop();

  // Устанавливаем uploadId только если он передан (новая загрузка)
  if (uploadId) {
    currentUploadId = uploadId;
  } else {
    // Для загрузки из истории currentUploadId будет установлен в loadSavedAnalysis
    currentUploadId = null;
  }

  // Показываем кнопку анализа
  if (analyzeButton) {
    analyzeButton.style.display = "inline-block";
    analyzeButton.textContent = "Отправить запрос";
    analyzeButton.disabled = false;
  }

  // Скрываем результат предыдущего анализа
  if (analysisResult) {
    analysisResult.style.display = "none";
    analysisResult.innerHTML = "";
  }

  // Пытаемся загрузить сохраненный анализ
  if (currentFilename) {
    loadSavedAnalysis(currentFilename);
  }
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(uploadUrl, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const { error } = await response.json();
      throw new Error(error || "Ошибка загрузки");
    }

    const { url, upload_id } = await response.json();
    updatePreview(url, upload_id);
  } catch (err) {
    console.error(err);
    alert(err.message || "Неизвестная ошибка");
  }
}

function handleFiles(files) {
  if (!files || !files.length) return;

  const [file] = files; // Берём только первый файл
  if (file.type.startsWith("image/")) {
    uploadFile(file);
  }
}

// -----------------------------------------------------------------------------
// События drag-and-drop
// -----------------------------------------------------------------------------
["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (e) => e.preventDefault(), false);
});

dropZone.addEventListener(
  "dragover",
  () => dropZone.classList.add("bg-secondary-subtle"),
  false,
);

dropZone.addEventListener(
  "dragleave",
  () => dropZone.classList.remove("bg-secondary-subtle"),
  false,
);

dropZone.addEventListener(
  "drop",
  (e) => {
    dropZone.classList.remove("bg-secondary-subtle");
    if (e.dataTransfer?.files) {
      handleFiles(e.dataTransfer.files);
    }
  },
  false,
);

// -----------------------------------------------------------------------------
// Клик по зоне
// -----------------------------------------------------------------------------
dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  if (fileInput.files) {
    handleFiles(fileInput.files);
    fileInput.value = ""; // сброс
  }
});

// -----------------------------------------------------------------------------
// Paste из буфера обмена
// -----------------------------------------------------------------------------
window.addEventListener("paste", (e) => {
  if (e.clipboardData) {
    const items = e.clipboardData.files;
    if (items.length) {
      handleFiles(items);
    }
  }
});

// -----------------------------------------------------------------------------
// Загрузка и сохранение анализа
// -----------------------------------------------------------------------------
async function loadSavedAnalysis(filename) {
  try {
    const response = await fetch(`/get_analysis/${filename}`);
    if (response.ok) {
      const data = await response.json();

      // Всегда устанавливаем upload_id, даже если нет сохраненных ингредиентов
      if (data.upload_id) {
        currentUploadId = data.upload_id;
      }

      if (data.ingredients && data.ingredients.trim()) {
        // Преобразуем markdown в HTML
        const htmlText = formatMarkdownToHtml(data.ingredients);

        if (analysisResult) {
          analysisResult.innerHTML = htmlText;
          analysisResult.style.display = "block";
        }

        if (analyzeButton) {
          analyzeButton.textContent = "Повторить анализ";
        }
      }
    }
  } catch (err) {
    console.error("Ошибка загрузки сохраненного анализа:", err);
  }
}

async function saveAnalysis(ingredients) {
  if (!currentUploadId) {
    console.error("Нет ID загрузки для сохранения");
    return;
  }

  try {
    const response = await fetch(saveAnalysisUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        upload_id: currentUploadId,
        ingredients: ingredients
      }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || "Ошибка сохранения");
    }
  } catch (err) {
    console.error("Ошибка сохранения анализа:", err);
  }
}

// -----------------------------------------------------------------------------
// Анализ изображения через chain-сервер
// -----------------------------------------------------------------------------
function formatMarkdownToHtml(markdownText) {
  return markdownText
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/_(.*?)_/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');
}

function renderAnalysisResult(analysis) {
  if (!analysisResult) return;

  const { dishes, total_weight, confidence } = analysis;

  let html = '<div class="analysis-result">';
  html += '<h5 class="mb-3">🍽️ Результат анализа</h5>';

  // Общая информация
  html += '<div class="row mb-3">';
  html += `<div class="col-md-6"><strong>Общая масса:</strong> ${total_weight} г</div>`;
  html += `<div class="col-md-6"><strong>Уверенность:</strong> ${(confidence * 100).toFixed(1)}%</div>`;
  html += '</div>';

  // Список блюд
  if (dishes && dishes.length > 0) {
    html += '<h6 class="mb-2">Обнаруженные блюда:</h6>';
    html += '<div class="list-group">';

    dishes.forEach((dish, index) => {
      const name = dish.name || 'Неизвестное блюдо';
      const weight = dish.weight_grams || 0;
      const description = dish.description || '';

      html += '<div class="list-group-item">';
      html += `<div class="d-flex w-100 justify-content-between">`;
      html += `<h6 class="mb-1">${index + 1}. ${name}</h6>`;
      html += `<small><strong>${weight} г</strong></small>`;
      html += '</div>';

      if (description) {
        html += `<p class="mb-1 text-muted">${description}</p>`;
      }
      html += '</div>';
    });

    html += '</div>';
  }

  html += '</div>';

  analysisResult.innerHTML = html;
  analysisResult.style.display = "block";
}

async function analyzeImage() {
  if (!analyzeButton || !analysisResult || !currentUploadId) return;

  // Показываем состояние загрузки
  analyzeButton.textContent = "Анализируем...";
  analyzeButton.disabled = true;

  // Показываем индикатор загрузки
  analysisResult.innerHTML = `
    <div class="text-center p-4">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Анализируем...</span>
      </div>
      <p class="mt-2 text-muted">Анализируем изображение с помощью ИИ...</p>
    </div>
  `;
  analysisResult.style.display = "block";

  try {
    const response = await fetch(analyzeImageUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        upload_id: currentUploadId
      }),
    });

    const data = await response.json();

    if (response.ok && data.success) {
      // Успешный анализ
      renderAnalysisResult(data.analysis);
      analyzeButton.textContent = "Повторить анализ";
    } else {
      // Ошибка анализа
      const errorMsg = data.error || "Произошла ошибка при анализе";
      analysisResult.innerHTML = `
        <div class="alert alert-danger" role="alert">
          <h6 class="alert-heading">❌ Ошибка анализа</h6>
          <p class="mb-0">${errorMsg}</p>
        </div>
      `;
      analyzeButton.textContent = "Попробовать снова";
    }
  } catch (err) {
    console.error("Ошибка при анализе:", err);
    analysisResult.innerHTML = `
      <div class="alert alert-danger" role="alert">
        <h6 class="alert-heading">❌ Ошибка соединения</h6>
        <p class="mb-0">Не удалось подключиться к серверу анализа. Попробуйте позже.</p>
      </div>
    `;
    analyzeButton.textContent = "Попробовать снова";
  } finally {
    analyzeButton.disabled = false;
  }
}

// Обработчик клика на кнопку анализа
if (analyzeButton) {
  analyzeButton.addEventListener("click", analyzeImage);
}

// -----------------------------------------------------------------------------
// Предзагрузка изображения из истории (если задано сервером)
// -----------------------------------------------------------------------------
if (window.PRELOAD_URL) {
  updatePreview(window.PRELOAD_URL);
}