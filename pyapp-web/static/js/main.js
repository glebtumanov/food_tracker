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
const queueAnalysisUrl = "/queue_analysis";
const queueNutrientsUrl = "/queue_nutrients";
const SINGLE_REQUEST_MODE = Boolean(window.__FEATURES__ && window.__FEATURES__.single_request_mode);

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
    nutrientsButton.disabled = SINGLE_REQUEST_MODE ? false : true;
    nutrientsButton.textContent = SINGLE_REQUEST_MODE ? "Определить нутриенты" : "Сначала проанализируйте изображение";
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
    nutrientsButton.disabled = SINGLE_REQUEST_MODE ? false : true;
    nutrientsButton.textContent = SINGLE_REQUEST_MODE ? "Определить нутриенты" : "Сначала проанализируйте изображение";
  }

  // Очищаем данные анализа
  currentAnalysisData = null;

  // Пытаемся загрузить сохраненный анализ
  if (currentFilename) {
    loadSavedAnalysis(currentFilename);
  }

  // Удаляем возможные нотификации-заменители кнопок
  const oldNotices = buttonContainer.querySelectorAll('.job-notice');
  oldNotices.forEach(n => n.remove());
  if (analyzeButton) analyzeButton.style.display = SINGLE_REQUEST_MODE ? 'none' : 'inline-block';
  if (nutrientsButton) nutrientsButton.style.display = 'inline-block';
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
        // Если есть JSON данные, используем современный шаблон отображения
        if (data.ingredients_json && nutrientsButton) {
          try {
            // Проверяем, является ли ingredients_json строкой или объектом
            if (typeof data.ingredients_json === 'string') {
              currentAnalysisData = JSON.parse(data.ingredients_json);
            } else {
              currentAnalysisData = data.ingredients_json;
            }

            // Отображаем результат в том же стиле, что и после анализа
            if (currentAnalysisData.dishes && currentAnalysisData.dishes.length > 0) {
              renderAnalysisResult(currentAnalysisData);
              nutrientsButton.disabled = false;
              nutrientsButton.textContent = "Определить нутриенты";
            } else {
              // Если нет блюд в JSON, используем fallback к markdown
              const htmlText = formatMarkdownToHtml(data.ingredients_md);
              if (analysisResult) {
                analysisResult.innerHTML = htmlText;
                analysisResult.style.display = "block";
              }
            }
          } catch (e) {
            console.error("Ошибка парсинга JSON данных:", e);
            // При ошибке используем fallback к markdown
            const htmlText = formatMarkdownToHtml(data.ingredients_md);
            if (analysisResult) {
              analysisResult.innerHTML = htmlText;
              analysisResult.style.display = "block";
            }
          }
        } else {
          // Если нет JSON данных, используем markdown
          const htmlText = formatMarkdownToHtml(data.ingredients_md);
          if (analysisResult) {
            analysisResult.innerHTML = htmlText;
            analysisResult.style.display = "block";
          }
        }

        if (analyzeButton) {
          analyzeButton.textContent = "Определить еду на картинке";
        }
      }

      // Если результата анализа нет, но есть активные джобы — покажем статус
      if ((!data.ingredients_md || !data.ingredients_md.trim()) && (data.job_id_analysis || data.job_id_full)) {
        const stA = data.job_status_analysis;
        const stF = data.job_status_full;
        if ((stA && stA !== 'done' && stA !== 'error') || (stF && stF !== 'done' && stF !== 'error')) {
          showInfoAlert("Запрос отправлен. Обновите страницу позже, чтобы увидеть результат.");
        }
      }

      // Если есть сохраненные данные нутриентов, отображаем их
      if (data.nutrients_json && Array.isArray(data.nutrients_json) && data.nutrients_json.length > 0) {
        // Конвертируем данные в формат, который ожидает renderNutrientResults
        const nutrientResults = data.nutrients_json.map(item => ({
          dish: {
            name: item.dish,
            amount: item.amount,
            unit_type: item.unit === 'gram' ? 'грамм' :
                       item.unit === 'pieces' ? 'штук' :
                       item.unit === 'piece' ? 'кусок' :
                       item.unit === 'slice' ? 'ломтик' :
                       item.unit === 'cup' ? 'чашка' : item.unit
          },
          nutrients: item.nutrients
        }));

        renderNutrientResults(nutrientResults);
      }

      // Если есть активная задача, и она не завершена — заменим кнопку на уведомление
      const hasActiveJob = ((data.job_id_full && data.job_status_full && data.job_status_full !== 'done' && data.job_status_full !== 'error') ||
                           (data.job_id_analysis && data.job_status_analysis && data.job_status_analysis !== 'done' && data.job_status_analysis !== 'error'));
      if (hasActiveJob) {
        showInfoAlert("Запрос отправлен. Обновите страницу позже, чтобы увидеть результат.");
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

  // Список блюд
  if (dishes && dishes.length > 0) {
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
  if (!analysisResult || !currentUploadId) return;

  // Определяем активную кнопку-триггер по режиму
  const triggerBtn = SINGLE_REQUEST_MODE ? nutrientsButton : analyzeButton;

  // Показываем состояние загрузки
  if (triggerBtn) {
    triggerBtn.textContent = "Анализируем...";
    triggerBtn.disabled = true;
  }

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
      if (triggerBtn) {
        triggerBtn.textContent = SINGLE_REQUEST_MODE ? "Определить нутриенты" : "Определить еду на картинке";
      }

      // В однозапросном режиме сервер уже возвращает нутриенты
      if (SINGLE_REQUEST_MODE && data.nutrients) {
        const results = (data.nutrients.dishes || []).map((nutr, i) => ({
          dish: {
            name: (currentAnalysisData.dishes[i]?.name_en) || (currentAnalysisData.dishes[i]?.name) || `Блюдо ${i+1}`,
            amount: currentAnalysisData.dishes[i]?.amount,
            unit_type: currentAnalysisData.dishes[i]?.unit_type,
          },
          nutrients: nutr,
        }));
        renderNutrientResults(results);
      }

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
      if (triggerBtn) {
        triggerBtn.textContent = SINGLE_REQUEST_MODE ? "Определить нутриенты" : "Определить еду на картинке";
      }
    }
  } catch (err) {
    console.error("Ошибка при анализе:", err);
    analysisResult.innerHTML = `
      <div class="alert alert-danger" role="alert">
        <h6 class="alert-heading">❌ Ошибка соединения</h6>
        <p class="mb-0">Не удалось подключиться к серверу анализа. Попробуйте позже.</p>
      </div>
    `;
          if (triggerBtn) {
            triggerBtn.textContent = SINGLE_REQUEST_MODE ? "Определить нутриенты" : "Определить еду на картинке";
          }
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
    }
  }
}

// -----------------------------------------------------------------------------
// Анализ нутриентов
// -----------------------------------------------------------------------------
async function analyzeNutrients() {
  if (!nutrientsButton || !nutrientsResult || !currentAnalysisData || !currentUploadId) return;

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
    // Подготавливаем данные для отправки всех блюд одним запросом
    const dishesData = [];

    for (const dish of dishes) {
      // Переводим единицы измерения на английский язык
      let unitInEnglish;
      switch (dish.unit_type) {
        case "штук":
          unitInEnglish = "pieces";
          break;
        case "кусок":
          unitInEnglish = "piece";
          break;
        case "ломтик":
          unitInEnglish = "slice";
          break;
        case "чашка":
          unitInEnglish = "cup";
          break;
        case "грамм":
          unitInEnglish = "gram";
          break;
        default:
          unitInEnglish = "gram";
          break;
      }

      dishesData.push({
        dish: dish.name_en || dish.name, // Используем английское название или русское
        amount: dish.amount || 100,
        unit: unitInEnglish
      });
    }

    // Отправляем один запрос для всех блюд
    const requestData = {
      dishes: dishesData,
      upload_id: currentUploadId // Добавляем upload_id для сохранения в БД
    };

    // Логируем запрос для отладки
    console.log(`🔍 Запрос нутриентов: ${dishes.length} блюд одним запросом`, dishesData);

    const response = await fetch(analyzeNutrientsUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestData),
    });

    // Проверяем на редирект (проблема с аутентификацией)
    if (response.redirected || response.url.includes('/login')) {
      nutrientsResult.innerHTML = `
        <div class="alert alert-warning" role="alert">
          <h6 class="alert-heading">🔐 Требуется авторизация</h6>
          <p class="mb-0">Сессия истекла. <a href="/login">Войдите в систему</a> заново.</p>
        </div>
      `;
      return;
    }

    if (response.ok) {
      const data = await response.json();

      if (data.error) {
        // Общая ошибка
        nutrientsResult.innerHTML = `
          <div class="alert alert-danger" role="alert">
            <h6 class="alert-heading">❌ Ошибка анализа нутриентов</h6>
            <p class="mb-0">${data.error}</p>
          </div>
        `;
      } else {
        // Успешный результат - преобразуем в старый формат для совместимости с renderNutrientResults
        const nutrientResults = [];

        if (data.dishes && Array.isArray(data.dishes)) {
          for (let i = 0; i < data.dishes.length; i++) {
            const dishResult = data.dishes[i];
            const originalDish = dishes[i]; // Соответствующее блюдо из анализа изображения

            if (dishResult.error) {
              nutrientResults.push({
                dish: originalDish,
                error: dishResult.error
              });
            } else {
              nutrientResults.push({
                dish: originalDish,
                nutrients: dishResult
              });
            }
          }
        }

        // Отображаем результаты
        renderNutrientResults(nutrientResults);

        // Логируем статистику
        const totalDishes = data.total_dishes || dishes.length;
        const successfulDishes = data.successful_dishes || nutrientResults.filter(r => !r.error).length;
        const failedDishes = data.failed_dishes || nutrientResults.filter(r => r.error).length;
        console.log(`📊 Результат анализа: всего=${totalDishes}, успешно=${successfulDishes}, ошибки=${failedDishes}`);
      }
    } else {
      // Ошибка HTTP
      let errorDetails = `Статус: ${response.status} ${response.statusText}`;

      // Пытаемся получить детали ошибки из ответа
      try {
        const errorData = await response.json();
        if (errorData.error) {
          errorDetails += `\nДетали: ${errorData.error}`;
        }
      } catch (e) {
        // Если не JSON, пытаемся получить текст
        try {
          const errorText = await response.text();
          if (errorText && errorText.length < 200) {
            errorDetails += `\nОтвет: ${errorText}`;
          }
        } catch (textError) {
          console.error('Не удалось прочитать ответ сервера:', textError);
        }
      }

      console.error('HTTP ошибка:', response.status, response.statusText, 'URL:', response.url);

      nutrientsResult.innerHTML = `
        <div class="alert alert-danger" role="alert">
          <h6 class="alert-heading">❌ Ошибка сервера</h6>
          <p class="mb-0" style="white-space: pre-line;">${errorDetails}</p>
        </div>
      `;
    }

  } catch (err) {
    console.error("Ошибка при анализе нутриентов:", err);
    nutrientsResult.innerHTML = `
      <div class="alert alert-danger" role="alert">
        <h6 class="alert-heading">❌ Ошибка соединения</h6>
        <p class="mb-0">Не удалось подключиться к серверу анализа. Попробуйте позже.</p>
      </div>
    `;
  } finally {
    nutrientsButton.textContent = "Определить нутриенты";
    nutrientsButton.disabled = false;
  }
}

function renderNutrientResults(results) {
  if (!nutrientsResult) return;

  // Подсчитываем суммарные значения
  let totalCalories = 0;
  let totalProtein = 0;
  let totalFat = 0;
  let totalCarbohydrates = 0;
  let totalFiber = 0;
  let successfulResults = 0;

  results.forEach((result) => {
    if (result.nutrients && !result.error) {
      const nutrients = result.nutrients;
      if (nutrients.calories !== undefined) {
        totalCalories += nutrients.calories;
      }
      if (nutrients.protein !== undefined) {
        totalProtein += nutrients.protein;
      }
      if (nutrients.fat !== undefined) {
        totalFat += nutrients.fat;
      }
      if (nutrients.carbohydrates !== undefined) {
        totalCarbohydrates += nutrients.carbohydrates;
      }
      if (nutrients.fiber !== undefined) {
        totalFiber += nutrients.fiber;
      }
      successfulResults++;
    }
  });

    let html = '<div class="nutrients-results">';
  html += '<h5 class="mb-3">🥗 Питательная ценность блюд</h5>';

  html += '<h6 class="mb-3">Детализация по блюдам:</h6>';

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
          <span class="label">🔥 Калории</span>
          <span class="value">${nutrients.calories.toFixed(1)} ккал</span>
        </div>`;
      }

      if (nutrients.protein !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">🥩 Белки</span>
          <span class="value">${nutrients.protein.toFixed(1)} г</span>
        </div>`;
      }

      if (nutrients.fat !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">🧈 Жиры</span>
          <span class="value">${nutrients.fat.toFixed(1)} г</span>
        </div>`;
      }

      if (nutrients.carbohydrates !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">🍞 Углеводы</span>
          <span class="value">${nutrients.carbohydrates.toFixed(1)} г</span>
        </div>`;
      }

      if (nutrients.fiber !== undefined) {
        html += `<div class="nutrient-stat">
          <span class="label">🌾 Клетчатка</span>
          <span class="value">${nutrients.fiber.toFixed(1)} г</span>
        </div>`;
      }

      html += '</div>';
    }

    html += '</div>';
  });

    // Добавляем суммарную информацию если есть успешные результаты
  if (successfulResults > 0) {
    html += '<div class="nutrient-item mt-4">';
    html += '<h6 class="text-primary">📊 Итог по всем блюдам на фото</h6>';
            html += '<div class="nutrient-stats">';

        if (totalCalories > 0) {
      html += `<div class="nutrient-stat">
        <span class="label">🔥 Калории</span>
        <span class="value">${totalCalories.toFixed(1)} ккал</span>
      </div>`;
    }

    if (totalProtein > 0) {
      html += `<div class="nutrient-stat">
        <span class="label">🥩 Белки</span>
        <span class="value">${totalProtein.toFixed(1)} г</span>
      </div>`;
    }

    if (totalFat > 0) {
      html += `<div class="nutrient-stat">
        <span class="label">🧈 Жиры</span>
        <span class="value">${totalFat.toFixed(1)} г</span>
      </div>`;
    }

    if (totalCarbohydrates > 0) {
      html += `<div class="nutrient-stat">
        <span class="label">🍞 Углеводы</span>
        <span class="value">${totalCarbohydrates.toFixed(1)} г</span>
      </div>`;
    }

    if (totalFiber > 0) {
      html += `<div class="nutrient-stat">
        <span class="label">🌾 Клетчатка</span>
        <span class="value">${totalFiber.toFixed(1)} г</span>
      </div>`;
    }

    html += '</div>';
    html += '</div>';
  }

  html += '</div>';

  nutrientsResult.innerHTML = html;
  nutrientsResult.style.display = "block";
}

// Обработчик клика на кнопку анализа
if (analyzeButton && !SINGLE_REQUEST_MODE) {
  analyzeButton.addEventListener("click", queueAnalyzeAsync);
}

// Обработчик клика на кнопку нутриентов
if (nutrientsButton) {
  // Всегда ставим задачу полного анализа на нутриенты
  nutrientsButton.addEventListener("click", queueNutrientsAsync);
}

// -----------------------------------------------------------------------------
// Предзагрузка изображения из истории (если задано сервером)
// -----------------------------------------------------------------------------
if (window.PRELOAD_URL) {
  updatePreview(window.PRELOAD_URL);
}

// -----------------------------------------------------------------------------
// Асинхронные очереди: постановка задач и уведомление пользователя
// -----------------------------------------------------------------------------
async function queueAnalyzeAsync() {
  if (!currentUploadId) return;
  const triggerBtn = SINGLE_REQUEST_MODE ? nutrientsButton : analyzeButton;
  try {
    // Показать сообщение немедленно, ещё до запроса
    showInfoAlert("Запрос отправлен. Обновите страницу позже, чтобы увидеть результат.");
    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.textContent = "Отправляем...";
    }
    const resp = await fetch(queueAnalysisUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_id: currentUploadId }),
      keepalive: true
    });
    const data = await resp.json();
    if (resp.ok && data.queued) {
      // Уже показали оповещение. Ничего не делаем.
    } else {
      showErrorAlert(data.error || "Не удалось поставить задачу в очередь");
    }
  } catch (e) {
    console.error(e);
    showErrorAlert("Ошибка соединения. Попробуйте позже.");
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = SINGLE_REQUEST_MODE ? "Определить нутриенты" : "Определить еду на картинке";
    }
  }
}

async function queueNutrientsAsync() {
  if (!currentUploadId) return;
  try {
    // Показать сообщение немедленно, ещё до запроса
    showInfoAlert("Запрос отправлен. Обновите страницу позже, чтобы увидеть результат.");
    nutrientsButton.disabled = true;
    nutrientsButton.textContent = "Отправляем...";
    const resp = await fetch(queueNutrientsUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_id: currentUploadId }),
      keepalive: true
    });
    const data = await resp.json();
    if (resp.ok && data.queued) {
      // Уже показали оповещение. Ничего не делаем.
    } else {
      showErrorAlert(data.error || "Не удалось поставить задачу в очередь");
    }
  } catch (e) {
    console.error(e);
    showErrorAlert("Ошибка соединения. Попробуйте позже.");
  } finally {
    nutrientsButton.disabled = false;
    nutrientsButton.textContent = "Определить нутриенты";
  }
}

function showInfoAlert(message) {
  // Отрисовываем подсказку вместо нажатой кнопки
  const notice = document.createElement('div');
  notice.className = 'alert alert-info job-notice';
  notice.innerHTML = `
    <h6 class="alert-heading">📤 Запрос отправлен</h6>
    <p class="mb-0">${message}</p>
  `;
  if (SINGLE_REQUEST_MODE) {
    if (nutrientsButton) {
      nutrientsButton.style.display = 'none';
      nutrientsButton.insertAdjacentElement('afterend', notice);
    } else if (analysisResult) {
      analysisResult.innerHTML = notice.outerHTML;
      analysisResult.style.display = 'block';
    }
  } else {
    if (analyzeButton) {
      analyzeButton.style.display = 'none';
      analyzeButton.insertAdjacentElement('afterend', notice);
    } else if (analysisResult) {
      analysisResult.innerHTML = notice.outerHTML;
      analysisResult.style.display = 'block';
    }
  }
}

function showErrorAlert(message) {
  if (!analysisResult) return;
  analysisResult.innerHTML = `
    <div class="alert alert-danger" role="alert">
      <h6 class="alert-heading">❌ Ошибка</h6>
      <p class="mb-0">${message}</p>
    </div>
  `;
  analysisResult.style.display = "block";
}