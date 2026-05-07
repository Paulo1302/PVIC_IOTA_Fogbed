module counter::counter {
    use iota::event;
    use iota::object::{Self, ID, UID};
    use iota::transfer;
    use iota::tx_context::{Self, TxContext};

    public struct CounterCreated has copy, drop {
        counter_id: ID,
        owner: address,
    }

    public struct CounterIncremented has copy, drop {
        counter_id: ID,
        new_value: u64,
    }

    public struct CounterReset has copy, drop {
        counter_id: ID,
    }

    public struct AdminCap has key, store {
        id: UID,
    }

    public struct Counter has key, store {
        id: UID,
        value: u64,
    }

    fun init(ctx: &mut TxContext) {
        transfer::transfer(
            AdminCap { id: object::new(ctx) },
            tx_context::sender(ctx),
        );
    }

    public entry fun create(ctx: &mut TxContext) {
        let counter = Counter {
            id: object::new(ctx),
            value: 0,
        };

        event::emit(CounterCreated {
            counter_id: object::id(&counter),
            owner: tx_context::sender(ctx),
        });

        transfer::share_object(counter);
    }

    public entry fun increment(counter: &mut Counter) {
        counter.value = counter.value + 1;

        event::emit(CounterIncremented {
            counter_id: object::id(counter),
            new_value: counter.value,
        });
    }

    public entry fun reset(counter: &mut Counter, _cap: &AdminCap) {
        counter.value = 0;

        event::emit(CounterReset {
            counter_id: object::id(counter),
        });
    }

    public fun get_value(counter: &Counter): u64 {
        counter.value
    }
}
