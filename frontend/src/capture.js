
/** Longest edge of the working copy. Small enough to be instant, large enough to be honest. */
const MAX_EDGE = 480

/** Longest edge of anything sent to the server. The model reads 224x224 after the
 *  server's own transform, extraction still has hundreds of pixels per signature at
 *  this size, and a phone's 12MP original is seconds of server CPU spent on pixels
 *  that are thrown away. */
const UPLOAD_MAX_EDGE = 2000

/** Below this mean luminance the server refuses the image outright. */
const DARK_MEAN = 80

/** How far under the mean a pixel must sit to count as ink. Adaptive, so a grey photo still works. */
const INK_OFFSET = 35

/** Pixels above this are clean white paper. */
const PAPER_LEVEL = 250

const MIN_PAPER_FRACTION = 0.2
const DIM_MEAN = 200

/** Below this share of ink there is nothing worth checking in the frame. */
const MIN_INK_FRACTION = 0.004

const UNREADABLE = Object.freeze({
  level: 'warning',
  title: 'Could not read the picture',
  message: 'Try photographing the signature again.',
})

function verdictFor({ mean, inkFraction, paperFraction }) {
  if (mean < DARK_MEAN) {
    return {
      level: 'error',
      title: 'Too dark',
      message: 'Move to better light or turn on the flash, then photograph the signature again.',
    }
  }
  if (inkFraction < MIN_INK_FRACTION) {
    return {
      level: 'error',
      title: 'No signature found',
      message: 'The picture looks blank. Fill the frame with the signature and photograph it again.',
    }
  }
  if (paperFraction < MIN_PAPER_FRACTION && mean < DIM_MEAN) {
    return {
      level: 'warning',
      title: 'Poor lighting',
      message: 'The paper looks grey, usually a shadow or dim light. Photograph the signature again in even light, without your own shadow across the page.',
    }
  }
  return {
    level: 'good',
    title: 'Looks good',
    message: 'The signature is clear enough to check.',
  }
}

/** Draws the image small and reads back the luminance of every pixel. */
function measure(image) {
  const longest = Math.max(image.naturalWidth || 0, image.naturalHeight || 0)
  if (!longest) return null

  const scale = Math.min(1, MAX_EDGE / longest)
  const width = Math.max(1, Math.round((image.naturalWidth || 0) * scale))
  const height = Math.max(1, Math.round((image.naturalHeight || 0) * scale))

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) return null
  context.drawImage(image, 0, 0, width, height)

  const { data } = context.getImageData(0, 0, width, height)
  const count = width * height
  const luminance = new Float32Array(count)

  let total = 0
  let paper = 0
  for (let i = 0; i < count; i += 1) {
    const offset = i * 4
    const value = 0.299 * data[offset] + 0.587 * data[offset + 1] + 0.114 * data[offset + 2]
    luminance[i] = value
    total += value
    if (value > PAPER_LEVEL) paper += 1
  }

  const mean = total / count
  const inkLevel = mean - INK_OFFSET
  let ink = 0
  for (let i = 0; i < count; i += 1) {
    if (luminance[i] < inkLevel) ink += 1
  }

  return { mean, inkFraction: ink / count, paperFraction: paper / count }
}

/**
 * A picked photograph, resized so its longest edge is at most UPLOAD_MAX_EDGE.
 * Anything that stops the resize — an odd format, an old browser, a corrupt file —
 * returns the original file untouched: the server accepts it either way, this is
 * only a saving.
 *
 * @param {File} file
 * @returns {Promise<File>}
 */
export async function downscaleForUpload(file) {
  if (!file || !file.type?.startsWith('image/') || typeof createImageBitmap !== 'function') {
    return file
  }
  let bitmap
  try {
    // from-image: bake the EXIF rotation in, or a portrait phone photo arrives sideways.
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    return file
  }
  try {
    const scale = UPLOAD_MAX_EDGE / Math.max(bitmap.width, bitmap.height)
    if (!Number.isFinite(scale) || scale >= 1) return file

    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const context = canvas.getContext('2d')
    if (!context) return file
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92))
    if (!blob) return file
    return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' })
  } catch {
    return file
  } finally {
    bitmap.close()
  }
}

/**
 * Look at a picked file and describe how usable it is.
 * Always resolves, never rejects, and never blocks submission.
 *
 * @param {File | Blob | null} file
 * @returns {Promise<{ level: 'good' | 'warning' | 'error', title: string, message: string }>}
 */
export function assessCapture(file) {
  return new Promise((resolve) => {
    if (!file) {
      resolve(UNREADABLE)
      return
    }

    let url = ''
    try {
      url = URL.createObjectURL(file)
    } catch {
      resolve(UNREADABLE)
      return
    }

    const image = new Image()

    const finish = (verdict) => {
      URL.revokeObjectURL(url)
      resolve(verdict)
    }

    image.onload = () => {
      try {
        const reading = measure(image)
        finish(reading ? verdictFor(reading) : UNREADABLE)
      } catch {
        finish(UNREADABLE)
      }
    }
    image.onerror = () => finish(UNREADABLE)
    image.src = url
  })
}
