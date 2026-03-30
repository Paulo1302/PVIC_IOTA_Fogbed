module counter::counter {
    use iota::object::{Self, UID};
    use iota::transfer;
    use iota::tx_context::{Self, TxContext};

    /// Counter object
    public struct Counter has key {
        id: UID,
        value: u64
    }

    /// Create new counter
    public entry fun create(ctx: &mut TxContext) {
        let counter = Counter {
            id: object::new(ctx),
            value: 0
        };
        transfer::share_object(counter);
    }

    /// Increment counter
    public entry fun increment(counter: &mut Counter) {
        counter.value = counter.value + 1;
    }

    /// Get counter value
    public fun get_value(counter: &Counter): u64 {
        counter.value
    }
}
