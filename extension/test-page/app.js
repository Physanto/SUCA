/**
 * @file Comportamiento de la página de prueba: menú, búsqueda, botones,
 * formulario y una pequeña tienda de una sola página. Todo ocurre en el
 * navegador; nada se envía por la red.
 *
 * Simula una aplicación evaluada cualquiera: no usa nada de la extensión.
 */

(function () {
  'use strict';

  const byId = (id) => document.getElementById(id);

  /** Productos de la búsqueda y de la tienda. */
  const PRODUCTS = [
    { id: 1, name: 'Audífonos inalámbricos', price: 180000 },
    { id: 2, name: 'Teclado mecánico', price: 250000 },
    { id: 3, name: 'Monitor de 27 pulgadas', price: 1200000 },
  ];
  const money = (value) => `$ ${value.toLocaleString('es-CO')}`;

  // Menú desplegable.
  const menuButton = byId('products-menu');
  menuButton.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    menuButton.setAttribute('aria-expanded', String(open));
    byId('products-submenu').hidden = !open;
  });

  // Búsqueda sobre la lista fija.
  byId('search-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const query = byId('search-input').value.trim().toLowerCase();
    const found = PRODUCTS.filter((product) => product.name.toLowerCase().includes(query));
    const list = byId('search-results');
    list.replaceChildren(
      ...(found.length > 0 ? found : [null]).map((product) => {
        const item = document.createElement('li');
        if (product === null) {
          item.textContent = 'No hay resultados.';
        } else {
          const link = document.createElement('a');
          link.href = `?view=product&id=${product.id}#aplicacion`;
          link.dataset.view = 'product';
          link.textContent = product.name;
          item.append(link);
        }
        return item;
      }),
    );
    byId('resultados').hidden = false;
  });

  // Botones.
  let clicks = 0;
  byId('counter-button').addEventListener('click', () => {
    clicks += 1;
    byId('counter-output').textContent = `${clicks} ${clicks === 1 ? 'clic' : 'clics'}`;
  });
  byId('slow-button').addEventListener('click', () => {
    // Responde después de 2 s: más tarde de lo que la captura espera una respuesta.
    setTimeout(() => {
      byId('slow-output').textContent = `Respondió a las ${new Date().toLocaleTimeString('es-CO')}`;
    }, 2000);
  });
  byId('toggle-button').addEventListener('click', () => {
    byId('notice').hidden = !byId('notice').hidden;
  });
  byId('close-notice').addEventListener('click', () => {
    byId('notice').hidden = true;
  });
  byId('prevented-link').addEventListener('click', (event) => event.preventDefault());

  // Formulario: validación nativa más una regla propia.
  const form = byId('signup-form');
  const confirm = byId('password-confirm');
  const checkPasswords = () => {
    const same = confirm.value === byId('password').value;
    confirm.setCustomValidity(same ? '' : 'Las contraseñas no coinciden.');
  };
  confirm.addEventListener('input', checkPasswords);
  byId('password').addEventListener('input', checkPasswords);
  form.addEventListener('submit', (event) => {
    // Solo llega aquí si pasó la validación del navegador. No se envía nada.
    event.preventDefault();
    byId('signup-output').hidden = false;
  });
  form.addEventListener('reset', () => {
    byId('signup-output').hidden = true;
    confirm.setCustomValidity('');
  });

  // Aplicación de una sola página: tienda con lista, detalle, carrito, pago y confirmación.
  const cart = new Map();
  let orderNumber = 1000;

  const element = (tag, attributes = {}, ...children) => {
    const node = document.createElement(tag);
    Object.assign(node, attributes);
    node.append(...children);
    return node;
  };
  const viewLink = (text, view, id) =>
    element('a', { href: `?view=${view}${id ? `&id=${id}` : ''}#aplicacion`, textContent: text, className: 'button-link' });

  const views = {
    products: () => [
      element('h3', { textContent: 'Productos' }),
      element(
        'ul',
        { className: 'products' },
        ...PRODUCTS.map((product) =>
          element('li', {}, `${product.name} · ${money(product.price)} `, viewLink('Ver detalle', 'product', product.id)),
        ),
      ),
    ],
    product: (params) => {
      const product = PRODUCTS.find((item) => item.id === Number(params.get('id'))) || PRODUCTS[0];
      const quantity = element('input', { type: 'number', min: 1, max: 10, value: 1, id: 'quantity' });
      const add = element('button', { type: 'button', textContent: 'Agregar al carrito' });
      add.addEventListener('click', () => {
        cart.set(product.id, (cart.get(product.id) || 0) + Number(quantity.value || 1));
        navigate('cart');
      });
      return [
        element('h3', { textContent: product.name }),
        element('p', { textContent: `Precio: ${money(product.price)}` }),
        element('label', { htmlFor: 'quantity', textContent: 'Cantidad ' }),
        quantity,
        add,
        element('p', {}, viewLink('Volver a productos', 'products')),
      ];
    },
    cart: () => {
      if (cart.size === 0) {
        return [element('h3', { textContent: 'Carrito' }), element('p', { textContent: 'El carrito está vacío.' })];
      }
      const items = [...cart].map(([id, count]) => {
        const product = PRODUCTS.find((item) => item.id === id);
        return element('li', { textContent: `${product.name} × ${count}` });
      });
      return [element('h3', { textContent: 'Carrito' }), element('ul', {}, ...items), viewLink('Comprar', 'checkout')];
    },
    checkout: () => {
      const pay = element('form', { className: 'form' });
      pay.append(
        element('fieldset', {},
          element('legend', { textContent: 'Método de pago' }),
          element('label', {}, element('input', { type: 'radio', name: 'payment', value: 'card', required: true }), ' Tarjeta de crédito'),
          element('label', {}, element('input', { type: 'radio', name: 'payment', value: 'transfer' }), ' Transferencia'),
        ),
        element('button', { type: 'submit', textContent: 'Confirmar compra' }),
      );
      pay.addEventListener('submit', (event) => {
        event.preventDefault();
        cart.clear();
        orderNumber += 1;
        navigate('confirmation', orderNumber);
      });
      return [element('h3', { textContent: 'Pago' }), pay];
    },
    confirmation: (params) => [
      element('h3', { textContent: 'Pedido confirmado' }),
      element('p', { textContent: `Número de pedido: ${params.get('id') || '—'}` }),
      viewLink('Seguir comprando', 'products'),
    ],
  };
  const titles = {
    products: 'Productos',
    product: 'Detalle del producto',
    cart: 'Carrito',
    checkout: 'Pago',
    confirmation: 'Pedido confirmado',
  };

  /** Dibuja la pantalla que indica la URL y actualiza el título de la página. */
  function render() {
    const params = new URLSearchParams(location.search);
    const view = params.get('view') in views ? params.get('view') : 'products';
    byId('app-view').replaceChildren(...views[view](params));
    byId('cart-count').textContent = String([...cart.values()].reduce((a, b) => a + b, 0));
    document.title = params.has('view') ? `${titles[view]} · Página de prueba` : 'Página de prueba · SUCA';
  }

  /** Cambia de pantalla sin recargar, como una aplicación de una sola página. */
  function navigate(view, id) {
    history.pushState(null, '', `?view=${view}${id ? `&id=${id}` : ''}#aplicacion`);
    render();
  }

  // Los enlaces a pantallas de la aplicación no recargan la página.
  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href^="?view="]');
    if (link) {
      event.preventDefault();
      history.pushState(null, '', link.getAttribute('href'));
      render();
      byId('aplicacion').scrollIntoView();
    }
  });
  window.addEventListener('popstate', render);
  render();
})();
