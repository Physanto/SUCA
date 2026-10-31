/**
 * @file Reglas de validación de los formularios. Cada función recibe los
 * valores del formulario y devuelve los errores por campo, con mensajes en
 * español que dicen qué corregir. Un objeto vacío significa que no hay errores.
 */

import { CITIES } from './data.js';

/**
 * @typedef {Object<string, string>} FieldErrors
 * Mensaje de error de cada campo inválido, por nombre del campo.
 */

/**
 * Deja solo los dígitos de un texto.
 *
 * @param {string} text - Texto con dígitos, espacios o guiones.
 * @returns {string} Solo los dígitos.
 */
export function digitsOnly(text) {
  return String(text ?? '').replace(/\D/g, '');
}

/**
 * Comprueba el dígito de control de un número de tarjeta (algoritmo de Luhn).
 *
 * @param {string} digits - Número de la tarjeta, solo dígitos.
 * @returns {boolean} Si el número es válido.
 */
export function passesLuhn(digits) {
  let sum = 0;
  for (let i = 0; i < digits.length; i += 1) {
    let digit = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 1) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    sum += digit;
  }
  return digits.length > 0 && sum % 10 === 0;
}

/**
 * Interpreta una fecha de vencimiento `MM/AA` (también `MM/AAAA`, `MMAA` o
 * `MM-AA`).
 *
 * @param {string} text - Fecha escrita por la persona.
 * @returns {{ month: number, year: number }|null} Mes y año completo, o `null`
 *   si no tiene el formato.
 */
export function parseExpiry(text) {
  const match = /^\s*(\d{1,2})\s*[/\-]?\s*(\d{2}|\d{4})\s*$/.exec(String(text ?? ''));
  if (!match) return null;
  const month = Number(match[1]);
  const year = match[2].length === 2 ? 2000 + Number(match[2]) : Number(match[2]);
  if (month < 1 || month > 12) return null;
  return { month, year };
}

/**
 * Valida los datos de envío.
 *
 * @param {{ name: string, street: string, city: string, phone: string }} values - Valores.
 * @returns {FieldErrors} Errores por campo.
 */
export function validateShipping(values) {
  const errors = {};
  if (!values.name.trim()) errors.name = 'Escribe el nombre de quien recibe el pedido.';
  if (values.street.trim().length < 5) {
    errors.street = 'Escribe la dirección completa, por ejemplo: Calle 10 # 20-30.';
  }
  if (!CITIES.includes(values.city)) errors.city = 'Elige la ciudad de entrega.';
  if (digitsOnly(values.phone).length !== 10) {
    errors.phone = 'Escribe un teléfono de 10 dígitos, por ejemplo: 300 123 4567.';
  }
  return errors;
}

/**
 * Interpreta una fecha de vencimiento solo con el formato `MM/AAAA` (regla
 * estricta de un problema sembrado).
 *
 * @param {string} text - Fecha escrita por la persona.
 * @returns {{ month: number, year: number }|null} Mes y año, o `null` si no
 *   tiene exactamente ese formato.
 */
export function parseExpiryStrict(text) {
  const match = /^\s*(\d{2})\/(\d{4})\s*$/.exec(String(text ?? ''));
  if (!match) return null;
  const month = Number(match[1]);
  return month >= 1 && month <= 12 ? { month, year: Number(match[2]) } : null;
}

/**
 * Valida los datos de pago.
 *
 * Por defecto acepta los formatos habituales (número con espacios o guiones,
 * vencimiento `MM/AA`, `MMAA` o `MM/AAAA`). Las reglas estrictas las activan
 * problemas sembrados.
 *
 * @param {{ method: string, number?: string, name?: string, expiry?: string,
 *   cvc?: string, bank?: string }} values - Valores; los de tarjeta solo se
 *   revisan si el método es `card`, y el banco si es `pse`.
 * @param {Date} now - Fecha actual, para saber si la tarjeta venció.
 * @param {{ digitsOnlyNumber?: boolean, fullYearExpiry?: boolean }} [rules] -
 *   `digitsOnlyNumber` rechaza espacios y guiones en el número;
 *   `fullYearExpiry` exige el vencimiento como `MM/AAAA`.
 * @returns {FieldErrors} Errores por campo.
 */
export function validatePayment(values, now, { digitsOnlyNumber = false, fullYearExpiry = false } = {}) {
  const errors = {};
  if (values.method === 'pse') {
    if (!values.bank) errors.bank = 'Elige tu banco.';
    return errors;
  }
  if (values.method !== 'card') {
    errors.method = 'Elige un método de pago.';
    return errors;
  }
  const number = digitsOnly(values.number);
  if (digitsOnlyNumber && /\D/.test(String(values.number ?? '').trim())) {
    errors.number = 'Escribe el número de la tarjeta sin espacios ni guiones.';
  } else if (number.length < 13 || number.length > 19 || !passesLuhn(number)) {
    errors.number = 'Revisa el número de la tarjeta: debe tener entre 13 y 19 dígitos.';
  }
  if (!String(values.name ?? '').trim()) {
    errors.name = 'Escribe el nombre como aparece en la tarjeta.';
  }
  const expiry = fullYearExpiry ? parseExpiryStrict(values.expiry) : parseExpiry(values.expiry);
  if (!expiry) {
    errors.expiry = fullYearExpiry
      ? 'Escribe el vencimiento con el formato MM/AAAA, por ejemplo: 12/2029.'
      : 'Escribe el vencimiento con el formato MM/AA, por ejemplo: 12/29.';
  } else if (
    expiry.year < now.getFullYear() ||
    (expiry.year === now.getFullYear() && expiry.month < now.getMonth() + 1)
  ) {
    errors.expiry = 'La tarjeta está vencida. Usa otra tarjeta.';
  }
  if (!/^\d{3,4}$/.test(String(values.cvc ?? '').trim())) {
    errors.cvc = 'El código de seguridad tiene 3 o 4 dígitos y está al respaldo de la tarjeta.';
  }
  return errors;
}

/**
 * Valida los datos personales de la cuenta.
 *
 * @param {{ name: string, phone: string }} values - Valores.
 * @returns {FieldErrors} Errores por campo.
 */
export function validateProfile(values) {
  const errors = {};
  if (values.name.trim().length < 3) errors.name = 'Escribe tu nombre completo.';
  if (digitsOnly(values.phone).length !== 10) {
    errors.phone = 'Escribe un teléfono de 10 dígitos, por ejemplo: 300 123 4567.';
  }
  return errors;
}

/**
 * Valida la dirección de envío de la cuenta.
 *
 * @param {{ street: string, city: string }} values - Valores.
 * @returns {FieldErrors} Errores por campo.
 */
export function validateAddress(values) {
  const errors = {};
  if (values.street.trim().length < 5) {
    errors.street = 'Escribe la dirección completa, por ejemplo: Calle 10 # 20-30.';
  }
  if (!CITIES.includes(values.city)) errors.city = 'Elige una ciudad de la lista.';
  return errors;
}
