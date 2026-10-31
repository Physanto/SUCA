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
 * Valida los datos de pago.
 *
 * @param {{ method: string, number?: string, name?: string, expiry?: string,
 *   cvc?: string, bank?: string }} values - Valores; los de tarjeta solo se
 *   revisan si el método es `card`, y el banco si es `pse`.
 * @param {Date} now - Fecha actual, para saber si la tarjeta venció.
 * @returns {FieldErrors} Errores por campo.
 */
export function validatePayment(values, now) {
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
  if (number.length < 13 || number.length > 19 || !passesLuhn(number)) {
    errors.number = 'Revisa el número de la tarjeta: debe tener entre 13 y 19 dígitos.';
  }
  if (!String(values.name ?? '').trim()) {
    errors.name = 'Escribe el nombre como aparece en la tarjeta.';
  }
  const expiry = parseExpiry(values.expiry);
  if (!expiry) {
    errors.expiry = 'Escribe el vencimiento con el formato MM/AA, por ejemplo: 12/29.';
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
