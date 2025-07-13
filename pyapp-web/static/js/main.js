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
const nutrientsButton = document.getElementById("nutrientsButton");
const nutrientsResult = document.getElementById("nutrientsResult");
const uploadUrl = "/upload";
const saveAnalysisUrl = "/save_analysis";
const analyzeImageUrl = "/analyze_image";
const analyzeNutrientsUrl = "/analyze_nutrients";

// Текущие данные загрузки
let currentUploadId = null;
let currentFilename = null;
let currentAnalysisData = null;

// Получаем ссылку на карточку предпросмотра и контейнер кнопок
const previewCard = previewContainer.querySelector('.card');
const buttonContainer = document.getElementById("buttonContainer");

if (!dropZone || !fileInput || !previewContainer || !previewCard || !buttonContainer || !nutrientsButton || !nutrientsResult) {
  /* DOM не загрузился корректно — прекращаем */
  throw new Error("Не удалось инициализировать элементы интерфейса");
}

// -----------------------------------------------------------------------------
// Вспомогательные функции
// -----------------------------------------------------------------------------
function updatePreview(url, uploadId = null) {
  if (!previewImage || !previewCard) return;

  previewImage.src = url;

  // Показываем карточку предпросмотра
  previewCard.style.display = "block";

  // Извлекаем имя файла из URL
  currentFilename = url.split('/').pop();

  // Устанавливаем uploadId только если он передан (новая загрузка)
  if (uploadId) {
    currentUploadId = uploadId;
  } else {
    // Для загрузки из истории currentUploadId будет установлен в loadSavedAnalysis
    currentUploadId = null;
  }

    // Показываем блок с кнопками и кнопку анализа
  if (buttonContainer) {
    buttonContainer.style.display = "block";
  }

  if (analyzeButton) {
    analyzeButton.textContent = "Определить еду на картинке";
    analyzeButton.disabled = false;
  }

  // Всегда показываем кнопку нутриентов при загрузке изображения
  if (nutrientsButton) {
    nutrientsButton.style.display = "inline-block";
    nutrientsButton.style.visibility = "visible";
    nutrientsButton.disabled = true;
    nutrientsButton.textContent = "Сначала проанализируйте изображение";
  }

  // Скрываем результаты предыдущего анализа
  if (analysisResult) {
    analysisResult.style.display = "none";
    analysisResult.innerHTML = "";
  }

  // Скрываем результаты нутриентов
  if (nutrientsResult) {
    nutrientsResult.style.display = "none";
    nutrientsResult.innerHTML = "";
  }

  // Сбрасываем состояние кнопки нутриентов
  if (nutrientsButton) {
    nutrientsButton.style.display = "inline-block";
    nutrientsButton.disabled = true;
    nutrientsButton.textContent = "Сначала проанализируйте изображение";
  }

  // Очищаем данные анализа
  currentAnalysisData = null;

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

      if (data.ingredients_md && data.ingredients_md.trim()) {
        // Преобразуем markdown в HTML
        const htmlText = formatMarkdownToHtml(data.ingredients_md);

        if (analysisResult) {
          analysisResult.innerHTML = htmlText;
          analysisResult.style.display = "block";
        }

        if (analyzeButton) {
          analyzeButton.textContent = "Определить еду на картинке";
        }

        // Если есть сохраненные JSON данные, активируем кнопку нутриентов
        if (data.ingredients_json && nutrientsButton) {
          try {
            // Проверяем, является ли ingredients_json строкой или объектом
            if (typeof data.ingredients_json === 'string') {
              currentAnalysisData = JSON.parse(data.ingredients_json);
            } else {
              currentAnalysisData = data.ingredients_json;
            }
            if (currentAnalysisData.dishes && currentAnalysisData.dishes.length > 0) {
              nutrientsButton.disabled = false;
              nutrientsButton.textContent = "Определить нутриенты";
            }
          } catch (e) {
            console.error("Ошибка парсинга JSON данных:", e);
          }
        }
      }
    }
  } catch (err) {
    console.error("Ошибка загрузки сохраненного анализа:", err);
  }
}

async function saveAnalysis(ingredients_md, ingredients_json = null) {
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
        ingredients_md: ingredients_md,
        ingredients_json: ingredients_json
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

  const { dishes, confidence } = analysis;

  let html = '<div class="analysis-result">';
  html += '<h5 class="mb-3">🍽️ Результат анализа</h5>';

  // Общая информация
  html += '<div class="row mb-3">';
  html += `<div class="col-md-12"><strong>Уверенность:</strong> ${(confidence * 100).toFixed(1)}%</div>`;
  html += '</div>';

  // Список блюд
  if (dishes && dishes.length > 0) {
    html += '<h6 class="mb-2">Обнаруженные блюда:</h6>';
    html += '<div class="list-group">';

    dishes.forEach((dish, index) => {
      const name = dish.name || 'Неизвестное блюдо';
      const name_en = dish.name_en || '';
      const description = dish.description || '';
      const description_en = dish.description_en || '';
      const unit_type = dish.unit_type || '';
      const amount = dish.amount || 0;

      html += '<div class="list-group-item">';
      html += `<div class="d-flex w-100 justify-content-between">`;
      html += `<h6 class="mb-1">${index + 1}. ${name}`;
      if (name_en) {
        html += ` <em class="text-muted">${name_en}</em>`;
      }
      html += '</h6>';

      if (unit_type && amount) {
        if (unit_type === 'штук') {
          html += `<small><strong>${amount.toFixed(0)} ${unit_type}</strong></small>`;
        } else {
          html += `<small><strong>${amount} ${unit_type}</strong></small>`;
        }
      }
      html += '</div>';

      if (description) {
        html += `<p class="mb-1 text-muted">${description}`;
        if (description_en) {
          html += ` <em>${description_en}</em>`;
        }
        html += '</p>';
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
      currentAnalysisData = data.analysis;
      renderAnalysisResult(data.analysis);
      analyzeButton.textContent = "Определить еду на картинке";

                  // Активируем кнопку нутриентов если есть блюда
      if (nutrientsButton) {
        if (data.analysis.dishes && data.analysis.dishes.length > 0) {
          nutrientsButton.disabled = false;
          nutrientsButton.textContent = "Определить нутриенты";
        } else {
          nutrientsButton.disabled = true;
          nutrientsButton.textContent = "Блюда не обнаружены";
        }
      }
    } else {
      // Ошибка анализа
      const errorMsg = data.error || "Произошла ошибка при анализе";
      analysisResult.innerHTML = `
        <div class="alert alert-danger" role="alert">
          <h6 class="alert-heading">❌ Ошибка анализа</h6>
          <p class="mb-0">${errorMsg}</p>
        </div>
      `;
      analyzeButton.textContent = "Определить еду на картинке";
    }
  } catch (err) {
    console.error("Ошибка при анализе:", err);
    analysisResult.innerHTML = `
      <div class="alert alert-danger" role="alert">
        <h6 class="alert-heading">❌ Ошибка соединения</h6>
        <p class="mb-0">Не удалось подключиться к серверу анализа. Попробуйте позже.</p>
      </div>
    `;
          analyzeButton.textContent = "Определить еду на картинке";
  } finally {
    analyzeButton.disabled = false;
  }
}

// -----------------------------------------------------------------------------
// Анализ нутриентов
// -----------------------------------------------------------------------------
async function analyzeNutrients() {
  if (!nutrientsButton || !nutrientsResult || !currentAnalysisData) return;

  const dishes = currentAnalysisData.dishes;
  if (!dishes || dishes.length === 0) {
    return;
  }

  // Показываем состояние загрузки
  nutrientsButton.textContent = "Анализируем...";
  nutrientsButton.disabled = true;

  // Показываем индикатор загрузки
  nutrientsResult.innerHTML = `
    <div class="text-center p-4">
      <div class="spinner-border text-success" role="status">
        <span class="visually-hidden">Анализируем нутриенты...</span>
      </div>
      <p class="mt-2 text-muted">Определяем питательную ценность блюд...</p>
    </div>
  `;
  nutrientsResult.style.display = "block";

  try {
    // Отправляем запросы для всех блюд
    const nutrientPromises = dishes.map(dish => {
      const requestData = {
        dish: dish.name_en || dish.name, // Используем английское название или русское
        amount: dish.amount || 100,
        unit: dish.unit_type === "штук" ? "грамм" :
              dish.unit_type === "кусок" ? "грамм" :
              dish.unit_type === "ломтик" ? "грамм" :
              dish.unit_type === "чашка" ? "грамм" : "грамм"
      };

      return fetch(analyzeNutrientsUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestData),
      });
    });

    // Ждем все ответы
    const responses = await Promise.all(nutrientPromises);

    // Обрабатываем результаты
    const nutrientResults = [];
    for (let i = 0; i < responses.length; i++) {
      const response = responses[i];
      const dish = dishes[i];

      if (response.ok) {
        const data = await response.json();
        if (data.error) {
          nutrientResults.push({
            dish: dish,
            error: data.error
          });
        } else {
          nutrientResults.push({
            dish: dish,
            nutrients: data
          });
        }
      } else {
        nutrientResults.push({
          dish: dish,
          error: `Ошибка HTTP: ${response.status}`
        });
      }
    }

    // Отображаем результаты
    renderNutrientResults(nutrientResults);
    nutrientsButton.textContent = "Определить нутриенты";

  } catch (err) {
    console.error("Ошибка при анализе нутриентов:", err);
    nutrientsResult.innerHTML = `
      <div class="alert alert-danger" role="alert">
        <h6 class="alert-heading">❌ Ошибка анализа нутриентов</h6>
        <p class="mb-0">Не удалось проанализировать питательную ценность блюд. Попробуйте позже.</p>
      </div>
    `;
    nutrientsButton.textContent = "Определить нутриенты";
  } finally {
    nutrientsButton.disabled = false;
  }
}

function renderNutrientResults(results) {
  if (!nutrientsResult) return;

  let html = '<div class="nutrients-results">';
  html += '<h5 class="mb-3">🥗 Питательная ценность блюд</h5>';

  results.forEach((result, index) => {
    const dish = result.dish;

    html += '<div class="nutrient-item">';
    html += `<h6>${dish.name}`;
    if (dish.amount && dish.unit_type) {
      html += ` (${dish.amount} ${dish.unit_type})`;
    }
    html += '</h6>';

    if (result.error) {
      html += `<div class="alert alert-warning mb-0" role="alert">
        <small>Ошибка: ${result.error}</small>
      </div>`;
    } else if (result.nutrients) {
      const nutrients = result.nutrients;
      html += '<div class="nutrient-stats">';

      if (nutrients.calories !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">Калории</span>
          <span class="value">${nutrients.calories.toFixed(1)} ккал</span>
        </div>`;
      }

      if (nutrients.protein !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">Белки</span>
          <span class="value">${nutrients.protein.toFixed(1)} г</span>
        </div>`;
      }

      if (nutrients.fat !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">Жиры</span>
          <span class="value">${nutrients.fat.toFixed(1)} г</span>
        </div>`;
      }

      if (nutrients.carbohydrates !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">Углеводы</span>
          <span class="value">${nutrients.carbohydrates.toFixed(1)} г</span>
        </div>`;
      }

      if (nutrients.fiber !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">Клетчатка</span>
          <span class="value">${nutrients.fiber.toFixed(1)} г</span>
        </div>`;
      }

      html += '</div>';
    }

    html += '</div>';
  });

  html += '</div>';

  nutrientsResult.innerHTML = html;
  nutrientsResult.style.display = "block";
}

// Обработчик клика на кнопку анализа
if (analyzeButton) {
  analyzeButton.addEventListener("click", analyzeImage);
}

// Обработчик клика на кнопку нутриентов
if (nutrientsButton) {
  nutrientsButton.addEventListener("click", analyzeNutrients);
}

// -----------------------------------------------------------------------------
// Предзагрузка изображения из истории (если задано сервером)
// -----------------------------------------------------------------------------
if (window.PRELOAD_URL) {
  updatePreview(window.PRELOAD_URL);
}