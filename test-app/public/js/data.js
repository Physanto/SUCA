/**
 * @file Datos falsos de la tienda: categorías, productos, la cuenta de
 * demostración y la tarjeta de prueba. Nada de esto es real: los precios están
 * en pesos colombianos y las marcas son inventadas.
 */

/**
 * @typedef {object} Category
 * @property {string} slug - Identificador de la categoría en la URL.
 * @property {string} name - Nombre visible.
 */

/**
 * @typedef {object} Product
 * @property {number} id - Identificador numérico (aparece en `/product/{id}`).
 * @property {string} name - Nombre visible.
 * @property {string} category - `slug` de su categoría.
 * @property {number} price - Precio en pesos.
 * @property {number|null} listPrice - Precio antes del descuento, o `null`.
 * @property {number} rating - Calificación promedio, de 1 a 5.
 * @property {number} reviews - Número de opiniones.
 * @property {string} image - Nombre del dibujo en `images/`, sin extensión.
 * @property {string} summary - Descripción corta.
 * @property {string[]} keywords - Palabras adicionales para la búsqueda.
 * @property {Array<[string, string]>} specs - Características: nombre y valor.
 */

/** @type {ReadonlyArray<Category>} */
export const CATEGORIES = Object.freeze([
  { slug: 'audio', name: 'Audio' },
  { slug: 'computers', name: 'Computadores' },
  { slug: 'phones', name: 'Celulares y relojes' },
  { slug: 'home', name: 'Hogar' },
]);

/**
 * Crea un producto inmutable.
 *
 * @param {Product} product - Datos del producto.
 * @returns {Readonly<Product>} El mismo producto, congelado.
 */
const product = (product) => Object.freeze(product);

/** @type {ReadonlyArray<Readonly<Product>>} */
export const PRODUCTS = Object.freeze([
  product({
    id: 101,
    name: 'Audífonos inalámbricos SoundMax',
    category: 'audio',
    price: 179900,
    listPrice: 219900,
    rating: 4.6,
    reviews: 312,
    image: 'headphones',
    summary: 'Audífonos de diadema con Bluetooth 5.3, cancelación de ruido y 40 horas de batería.',
    keywords: ['auriculares', 'bluetooth', 'diadema'],
    specs: [
      ['Conexión', 'Bluetooth 5.3 y cable de 3,5 mm'],
      ['Batería', 'Hasta 40 horas'],
      ['Cancelación de ruido', 'Activa, con modo ambiente'],
      ['Peso', '250 g'],
    ],
  }),
  product({
    id: 102,
    name: 'Audífonos inalámbricos Brisa Pro',
    category: 'audio',
    price: 249900,
    listPrice: null,
    rating: 4.4,
    reviews: 128,
    image: 'earbuds',
    summary: 'Audífonos de botón con estuche de carga, resistentes al agua y al sudor.',
    keywords: ['auriculares', 'bluetooth', 'boton', 'deportivos'],
    specs: [
      ['Conexión', 'Bluetooth 5.2'],
      ['Batería', '8 horas, 32 con el estuche'],
      ['Resistencia', 'IPX5'],
      ['Peso', '5 g cada uno'],
    ],
  }),
  product({
    id: 103,
    name: 'Audífonos inalámbricos de diadema Onda',
    category: 'audio',
    price: 319900,
    listPrice: 359900,
    rating: 4.7,
    reviews: 86,
    image: 'headphones',
    summary: 'Sonido de estudio, almohadillas de espuma viscoelástica y estuche rígido.',
    keywords: ['auriculares', 'bluetooth', 'estudio'],
    specs: [
      ['Conexión', 'Bluetooth 5.3 y USB-C'],
      ['Batería', 'Hasta 30 horas'],
      ['Cancelación de ruido', 'Activa'],
      ['Peso', '290 g'],
    ],
  }),
  product({
    id: 104,
    name: 'Parlante portátil Ritmo Mini',
    category: 'audio',
    price: 129900,
    listPrice: null,
    rating: 4.3,
    reviews: 204,
    image: 'speaker',
    summary: 'Parlante resistente al agua, del tamaño de una mano, con 12 horas de batería.',
    keywords: ['altavoz', 'bocina', 'bluetooth'],
    specs: [
      ['Potencia', '10 W'],
      ['Batería', '12 horas'],
      ['Resistencia', 'IP67'],
    ],
  }),
  product({
    id: 105,
    name: 'Barra de sonido Cine 2.1',
    category: 'audio',
    price: 689900,
    listPrice: 799900,
    rating: 4.5,
    reviews: 57,
    image: 'soundbar',
    summary: 'Barra de sonido con subwoofer inalámbrico y conexión HDMI ARC.',
    keywords: ['televisor', 'teatro en casa', 'subwoofer'],
    specs: [
      ['Potencia', '300 W'],
      ['Conexiones', 'HDMI ARC, óptica y Bluetooth'],
    ],
  }),
  product({
    id: 106,
    name: 'Audífonos con cable Básicos',
    category: 'audio',
    price: 39900,
    listPrice: null,
    rating: 4.0,
    reviews: 410,
    image: 'earbuds',
    summary: 'Audífonos de botón con micrófono y control de volumen en el cable.',
    keywords: ['auriculares', 'manos libres'],
    specs: [
      ['Conexión', 'Cable de 3,5 mm'],
      ['Largo del cable', '1,2 m'],
    ],
  }),
  product({
    id: 201,
    name: 'Portátil Altura 14',
    category: 'computers',
    price: 2899000,
    listPrice: 3199000,
    rating: 4.5,
    reviews: 73,
    image: 'laptop',
    summary: 'Portátil liviano de 14 pulgadas, 16 GB de memoria y 512 GB de almacenamiento.',
    keywords: ['computador', 'laptop', 'notebook'],
    specs: [
      ['Pantalla', '14" Full HD'],
      ['Memoria', '16 GB'],
      ['Almacenamiento', 'SSD de 512 GB'],
      ['Peso', '1,3 kg'],
    ],
  }),
  product({
    id: 202,
    name: 'Portátil Altura 16 Pro',
    category: 'computers',
    price: 4299000,
    listPrice: null,
    rating: 4.6,
    reviews: 41,
    image: 'laptop',
    summary: 'Pantalla de 16 pulgadas, 32 GB de memoria y tarjeta gráfica dedicada.',
    keywords: ['computador', 'laptop', 'notebook', 'gamer'],
    specs: [
      ['Pantalla', '16" QHD'],
      ['Memoria', '32 GB'],
      ['Almacenamiento', 'SSD de 1 TB'],
      ['Peso', '2,1 kg'],
    ],
  }),
  product({
    id: 203,
    name: 'Monitor Nítido de 27 pulgadas',
    category: 'computers',
    price: 1199000,
    listPrice: 1349000,
    rating: 4.4,
    reviews: 95,
    image: 'monitor',
    summary: 'Monitor QHD de 27 pulgadas con panel IPS y base ajustable en altura.',
    keywords: ['pantalla', 'qhd'],
    specs: [
      ['Resolución', '2560 × 1440'],
      ['Panel', 'IPS, 75 Hz'],
      ['Conexiones', 'HDMI y DisplayPort'],
    ],
  }),
  product({
    id: 204,
    name: 'Teclado mecánico Tecla K2',
    category: 'computers',
    price: 289900,
    listPrice: null,
    rating: 4.7,
    reviews: 152,
    image: 'keyboard',
    summary: 'Teclado mecánico compacto, inalámbrico, con distribución en español.',
    keywords: ['mecanico', 'gamer', 'inalambrico'],
    specs: [
      ['Distribución', 'Español (Latinoamérica)'],
      ['Conexión', 'Bluetooth y USB-C'],
    ],
  }),
  product({
    id: 205,
    name: 'Mouse inalámbrico Ágil',
    category: 'computers',
    price: 89900,
    listPrice: 109900,
    rating: 4.2,
    reviews: 268,
    image: 'mouse',
    summary: 'Mouse silencioso y ergonómico con receptor USB y batería recargable.',
    keywords: ['raton', 'inalambrico'],
    specs: [
      ['Conexión', 'Receptor USB de 2,4 GHz'],
      ['Batería', 'Recargable, hasta 60 días'],
    ],
  }),
  product({
    id: 206,
    name: 'Base refrigerante para portátil',
    category: 'computers',
    price: 79900,
    listPrice: null,
    rating: 3.9,
    reviews: 64,
    image: 'laptop',
    summary: 'Base con dos ventiladores silenciosos y cinco alturas.',
    keywords: ['ventilador', 'soporte'],
    specs: [['Ventiladores', '2, de 140 mm']],
  }),
  product({
    id: 301,
    name: 'Celular Faro 6 de 128 GB',
    category: 'phones',
    price: 1299000,
    listPrice: 1499000,
    rating: 4.5,
    reviews: 389,
    image: 'phone',
    summary: 'Pantalla de 6,5 pulgadas, cámara de 50 MP y batería para dos días.',
    keywords: ['telefono', 'smartphone', 'movil'],
    specs: [
      ['Pantalla', '6,5" OLED'],
      ['Almacenamiento', '128 GB'],
      ['Cámara', '50 MP'],
    ],
  }),
  product({
    id: 302,
    name: 'Celular Faro 6 Plus de 256 GB',
    category: 'phones',
    price: 1799000,
    listPrice: null,
    rating: 4.6,
    reviews: 144,
    image: 'phone',
    summary: 'Pantalla de 6,8 pulgadas, triple cámara y carga rápida de 45 W.',
    keywords: ['telefono', 'smartphone', 'movil'],
    specs: [
      ['Pantalla', '6,8" OLED'],
      ['Almacenamiento', '256 GB'],
      ['Cámara', 'Triple, 50 MP'],
    ],
  }),
  product({
    id: 303,
    name: 'Cargador rápido de 30 W',
    category: 'phones',
    price: 69900,
    listPrice: null,
    rating: 4.3,
    reviews: 221,
    image: 'charger',
    summary: 'Cargador USB-C compatible con carga rápida, con cable de 1 m.',
    keywords: ['usb', 'carga'],
    specs: [['Potencia', '30 W']],
  }),
  product({
    id: 304,
    name: 'Funda protectora para Faro 6',
    category: 'phones',
    price: 49900,
    listPrice: null,
    rating: 4.1,
    reviews: 97,
    image: 'phone',
    summary: 'Funda de silicona con bordes reforzados.',
    keywords: ['estuche', 'carcasa', 'protector'],
    specs: [['Material', 'Silicona']],
  }),
  product({
    id: 305,
    name: 'Reloj inteligente Pulso 2',
    category: 'phones',
    price: 399900,
    listPrice: 459900,
    rating: 4.4,
    reviews: 176,
    image: 'watch',
    summary: 'Mide pasos, ritmo cardíaco y sueño; batería de 10 días.',
    keywords: ['smartwatch', 'deportivo', 'pulsera'],
    specs: [
      ['Pantalla', '1,4" AMOLED'],
      ['Batería', 'Hasta 10 días'],
    ],
  }),
  product({
    id: 306,
    name: 'Tableta Lienzo de 10 pulgadas',
    category: 'phones',
    price: 999000,
    listPrice: null,
    rating: 4.2,
    reviews: 58,
    image: 'tablet',
    summary: 'Tableta de 10 pulgadas con lápiz incluido.',
    keywords: ['tablet', 'ipad'],
    specs: [
      ['Pantalla', '10,4"'],
      ['Almacenamiento', '128 GB'],
    ],
  }),
  product({
    id: 401,
    name: 'Lámpara de escritorio Luma',
    category: 'home',
    price: 119900,
    listPrice: null,
    rating: 4.5,
    reviews: 83,
    image: 'lamp',
    summary: 'Lámpara LED con tres tonos de luz y brazo articulado.',
    keywords: ['luz', 'led', 'estudio'],
    specs: [['Potencia', '8 W']],
  }),
  product({
    id: 402,
    name: 'Cafetera de goteo Aroma',
    category: 'home',
    price: 189900,
    listPrice: 229900,
    rating: 4.3,
    reviews: 132,
    image: 'coffee',
    summary: 'Cafetera para 12 tazas con jarra térmica y apagado automático.',
    keywords: ['cafe', 'greca'],
    specs: [['Capacidad', '12 tazas']],
  }),
  product({
    id: 403,
    name: 'Bombillo inteligente Wi-Fi',
    category: 'home',
    price: 59900,
    listPrice: null,
    rating: 4.0,
    reviews: 245,
    image: 'lamp',
    summary: 'Bombillo de colores que se controla desde el celular.',
    keywords: ['luz', 'led', 'wifi', 'foco'],
    specs: [['Potencia', '9 W']],
  }),
  product({
    id: 404,
    name: 'Purificador de aire Brisa',
    category: 'home',
    price: 549900,
    listPrice: 629900,
    rating: 4.6,
    reviews: 39,
    image: 'purifier',
    summary: 'Filtro HEPA para espacios de hasta 30 m², silencioso de noche.',
    keywords: ['aire', 'filtro', 'hepa'],
    specs: [['Área', 'Hasta 30 m²']],
  }),
  product({
    id: 405,
    name: 'Hervidor eléctrico de 1,7 L',
    category: 'home',
    price: 99900,
    listPrice: null,
    rating: 4.2,
    reviews: 118,
    image: 'kettle',
    summary: 'Hervidor de acero inoxidable con apagado automático.',
    keywords: ['tetera', 'agua'],
    specs: [['Capacidad', '1,7 L']],
  }),
  product({
    id: 406,
    name: 'Ventilador de torre Silencio',
    category: 'home',
    price: 279900,
    listPrice: null,
    rating: 4.1,
    reviews: 71,
    image: 'purifier',
    summary: 'Ventilador de torre con control remoto y tres velocidades.',
    keywords: ['aire', 'torre'],
    specs: [['Velocidades', '3']],
  }),
]);

/** Ciudades disponibles para los envíos. */
export const CITIES = Object.freeze([
  'Barranquilla',
  'Bogotá',
  'Bucaramanga',
  'Cali',
  'Cartagena',
  'Manizales',
  'Medellín',
  'Pereira',
]);

/**
 * Cuenta de demostración. El participante la ve en la pantalla de inicio de
 * sesión, así nunca escribe datos propios.
 */
export const DEMO_ACCOUNT = Object.freeze({
  email: 'ana.gomez@correo.test',
  password: 'Ceiba2026',
  name: 'Ana Gómez',
  phone: '300 123 4567',
  // Sin apartamento ni referencia: la tarea de cambiar la dirección da solo
  // calle y ciudad, y un dato de más hacía dudar si también había que cambiarlo.
  address: Object.freeze({ street: 'Carrera 7 # 45-12', city: 'Medellín', details: '' }),
});

/** Tarjeta de prueba que se muestra en el pago. Cumple el algoritmo de Luhn. */
export const TEST_CARD = Object.freeze({
  number: '4111 1111 1111 1111',
  name: 'ANA GOMEZ',
  expiry: '12/29',
  cvc: '123',
});

/** Bancos de la transferencia (PSE). */
export const BANKS = Object.freeze([
  'Banco Andino',
  'Banco del Valle',
  'Cooperativa Central',
  'Banco Caribe',
]);

/** Costo del envío cuando el subtotal no alcanza el envío gratis. */
export const SHIPPING_COST = 12900;

/** Subtotal desde el cual el envío es gratis. */
export const FREE_SHIPPING_FROM = 150000;

/** Número del primer pedido. */
export const FIRST_ORDER_ID = 5012;

/** Unidades máximas de un producto en el carrito. */
export const MAX_QUANTITY = 10;

/**
 * Productos destacados de la portada, en orden. No incluye audífonos
 * inalámbricos: la tarea 1 pide buscarlos, y un destacado sería un atajo que
 * se salta la búsqueda (por lo mismo no hay sugerencias mientras se escribe).
 */
export const FEATURED_PRODUCTS = Object.freeze([105, 201, 301, 402, 104, 305, 204, 401]);

/**
 * Busca un producto por su identificador.
 *
 * @param {number} id - Identificador del producto.
 * @returns {Readonly<Product>|undefined} El producto, si existe.
 */
export function findProduct(id) {
  return PRODUCTS.find((item) => item.id === id);
}

/**
 * Busca una categoría por su `slug`.
 *
 * @param {string} slug - Identificador de la categoría.
 * @returns {Category|undefined} La categoría, si existe.
 */
export function findCategory(slug) {
  return CATEGORIES.find((item) => item.slug === slug);
}
