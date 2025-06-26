// -----------------------------------------------------------------------------
// Основные элементы
// -----------------------------------------------------------------------------
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const previewContainer = document.getElementById("previewContainer");
/* Элементы статического шаблона превью */
const previewImage = document.getElementById("previewImage");
const previewText1 = document.getElementById("previewText1");
const previewText2 = document.getElementById("previewText2");
const uploadUrl = "/upload";

if (!dropZone || !fileInput || !previewContainer) {
  /* DOM не загрузился корректно — прекращаем */
  throw new Error("Не удалось инициализировать элементы интерфейса");
}

// -----------------------------------------------------------------------------
// Вспомогательные функции
// -----------------------------------------------------------------------------
function updatePreview(url) {
  if (!previewImage) return;

  previewImage.src = url;
  previewImage.classList.remove("d-none");

  /* При необходимости можно заменить текст на результат ML-модели */
  if (previewText1) {
    previewText1.textContent =
      "Lorem ipsum dolor sit amet, consectetur adipiscing elit.";
  }
  if (previewText2) {
    previewText2.textContent =
      "Suspendisse potenti. Integer sit amet velit sed orci convallis tristique.";
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

    const { url } = await response.json();
    updatePreview(url);
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
// Предзагрузка изображения из истории (если задано сервером)
// -----------------------------------------------------------------------------
if (window.PRELOAD_URL) {
  updatePreview(window.PRELOAD_URL);
}