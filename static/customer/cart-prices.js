function refreshCartPrices(cart, prices) {
    let updated = false;
    let unavailable = false;
    if (!prices || typeof prices !== "object") {
        return {updated: false, unavailable: true};
    }
    cart.forEach(function(item) {
        if (!Object.prototype.hasOwnProperty.call(prices, item.name)) {
            unavailable = true;
            return;
        }
        const price = Number(prices[item.name]);
        if (Number(item.price) !== price) {
            item.price = price;
            updated = true;
        }
    });
    return {updated: updated, unavailable: unavailable};
}
